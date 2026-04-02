from __future__ import annotations

import ctypes
import ctypes.util
import os
import select
import sys
import time
from pathlib import Path

_IN_MODIFY = 0x00000002  # data was written to the file
_IN_CLOSE_WRITE = 0x00000008  # file handle was closed after writing
_IN_MOVE_SELF = 0x00000800  # the file itself was renamed (log rotation)
_IN_DELETE_SELF = 0x00000400  # the file itself was deleted (log rotation)

# The combined mask we pass to inotify_add_watch.
_WATCH_FLAGS = _IN_MODIFY | _IN_CLOSE_WRITE | _IN_MOVE_SELF | _IN_DELETE_SELF


def _init_libc():
    """Find and load libc, declare the inotify function signatures, return it.

    ctypes.util.find_library("c") locates the system C library (`libc.so.6`
    on most Linux systems). We load it with `CDLL` and then declare the types
    of the three `inotify` functions we need, which tells ctypes how to pass
    arguments and read return values correctly.

    Returns None if the library can't be found or if inotify isn't available
    (the functions don't exist on macOS, for example).
    """
    lib_name = ctypes.util.find_library("c")
    if not lib_name:
        return None
    try:
        libc = ctypes.CDLL(lib_name, use_errno=True)
        # Declare argument and return types for each inotify function.
        # Without this, ctypes defaults to int for everything, which breaks
        # on 64-bit systems where pointers aren't ints.
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_add_watch.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        libc.inotify_rm_watch.restype = ctypes.c_int
        libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        return libc
    except OSError, AttributeError:
        return None


_libc = _init_libc()
_INOTIFY_AVAILABLE = _libc is not None


class _InotifyWatcher:
    """Wraps a single inotify watch on one file.

    inotify works with file descriptors: inotify_init1() creates an inotify
    instance (returned as an fd), and inotify_add_watch() registers a file
    to watch on that instance. When a watched event occurs, the kernel writes
    an event record to the inotify fd, making it readable.

    We use select() to wait for the fd to become readable, which blocks the
    thread with zero CPU usage until an event arrives or the timeout expires.
    """

    def __init__(self, log_file: Path) -> None:
        # Create a new inotify instance. The fd is like any other file
        # descriptor — we can select() on it and must close it when done.
        self._inotify_fd = _libc.inotify_init1(0)
        if self._inotify_fd < 0:
            raise OSError("inotify_init1 failed. inotify not available!")

        # Register the log file as a watch target with our event flags.
        # Returns a watch descriptor (wd) we need to remove it later.
        self._watch_desc = _libc.inotify_add_watch(
            self._inotify_fd,
            str(log_file).encode(),  # path as bytes
            _WATCH_FLAGS,
        )
        if self._watch_desc < 0:
            os.close(self._inotify_fd)
            raise OSError(f"inotify_add_watch failed for: {log_file}")

    def wait_for_change(self, timeout_secs: float = 1.0) -> bool:
        """Block until the watched file changes or the timeout expires.

        Returns True if a change event arrived (there may be new bytes to read),
        False if we timed out with no event.

        select() is used instead of a blocking read() for two reasons:
          1. It accepts a timeout, so we can wake up periodically even if
             the process is producing no output (e.g. to re-check if it's alive).
          2. It's interruptible by signals — specifically SIGINT from Ctrl+C,
             which is how the user detaches from `sualw toggle`.
        """
        readable, _, _ = select.select([self._inotify_fd], [], [], timeout_secs)
        if readable:
            # Drain the inotify event buffer. We don't inspect the events —
            # any event on our watched file means "go check for new bytes".
            try:
                os.read(self._inotify_fd, 4096)
            except OSError:
                pass
            return True
        return False

    def close(self) -> None:
        """Remove the watch and close the inotify file descriptor.

        Always call this when done, or the kernel holds the watch open
        until the process exits (small leak but bad practice).
        """
        try:
            _libc.inotify_rm_watch(self._inotify_fd, self._watch_desc)
        except Exception:
            pass
        try:
            os.close(self._inotify_fd)
        except OSError:
            pass


def tail_log(log_file: Path, *, from_start: bool = False) -> None:
    """Stream log_file to stdout. Blocks until the user presses Ctrl+C.

    from_start=False  jump to the end of the file first, then stream only
                        new output.

    from_start=True   replay all existing content first, then continue
                        streaming live.
    """
    if not log_file.exists():
        sys.stderr.write(f"[sualw] log not found: {log_file}\n")
        return

    if _INOTIFY_AVAILABLE:
        _tail_with_inotify(log_file, from_start=from_start)
    else:
        _tail_with_polling(log_file, from_start=from_start)


def _open_log_file(log_file: Path, from_start: bool):
    """Open the log file in binary mode and seek to the right position.

    Binary mode is used so we can write raw bytes to sys.stdout.buffer,
    which avoids any encoding issues from the child process output.

    Returns (file_handle, inode_number). The inode is used to detect
    log rotation — if the inode changes, a new file replaced the old one.
    """
    log_handle = open(log_file, "rb")
    file_inode = os.fstat(log_handle.fileno()).st_ino
    if not from_start:
        log_handle.seek(0, 2)  # os.SEEK_END will jump to the very end
    return log_handle, file_inode


def _flush_new_bytes(log_handle, file_inode: int) -> tuple[int, bool]:
    """Read all currently available bytes from log_handle and write to stdout.

    Also detects log rotation by comparing the file's current inode to the
    one we opened. If the inode changed, the original file was replaced
    (moved or deleted) by a new one with the same path.

    Returns (current_inode, was_rotated):
      current_inode — inode of whatever is now at the file's path
      was_rotated   — True if the file was replaced, caller should reopen
    """
    new_bytes = log_handle.read()
    if new_bytes:
        sys.stdout.buffer.write(new_bytes)
        sys.stdout.buffer.flush()

    # Check if the path now points to a different file (rotation).
    try:
        current_inode = os.stat(log_handle.name).st_ino
    except OSError:
        # File is gone entirely.
        return file_inode, True

    if current_inode != file_inode:
        # A different file now lives at this path.
        return current_inode, True

    return file_inode, False


def _tail_with_inotify(log_file: Path, *, from_start: bool) -> None:
    """
    Stream using `inotify`: block until the kernel signals a write, then read.

    The 1-second timeout on wait_for_change() means we wake up at least
    once per second even if nothing is written, which lets us detect
    log rotation promptly and keeps the loop responsive to shutdown.
    """
    log_handle, file_inode = _open_log_file(log_file, from_start)
    watcher = _InotifyWatcher(log_file)
    try:
        while True:
            watcher.wait_for_change(timeout_secs=1.0)
            file_inode, was_rotated = _flush_new_bytes(log_handle, file_inode)
            if was_rotated:
                # The log file was replaced. Close everything and reopen.
                log_handle.close()
                watcher.close()
                time.sleep(0.2)  # brief pause for the new file to appear
                if not log_file.exists():
                    return  # file is gone and not coming back
                log_handle, file_inode = _open_log_file(log_file, from_start=True)
                watcher = _InotifyWatcher(log_file)
    finally:
        log_handle.close()
        watcher.close()


def _tail_with_polling(log_file: Path, *, from_start: bool) -> None:
    """Stream using a sleep loop: read, sleep, repeat.

    Used when inotify isn't available. The sleep duration backs off
    exponentially when the process produces no output — from 20ms up to
    200ms — to avoid burning CPU on a quiet process.
    """
    log_handle, file_inode = _open_log_file(log_file, from_start)
    consecutive_empty_reads = 0
    try:
        while True:
            file_inode, was_rotated = _flush_new_bytes(log_handle, file_inode)
            if was_rotated:
                log_handle.close()
                time.sleep(0.2)
                if not log_file.exists():
                    return
                log_handle, file_inode = _open_log_file(log_file, from_start=True)
                consecutive_empty_reads = 0
            else:
                consecutive_empty_reads += 1
                # Sleep longer the more empty reads we've had in a row.
                # min() caps it at 200ms so we don't wait too long between checks.
                sleep_secs = min(0.02 * (1.5**consecutive_empty_reads), 0.2)
                time.sleep(sleep_secs)
    finally:
        log_handle.close()
