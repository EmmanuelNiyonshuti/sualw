from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import registry


class CommandNotFoundError(Exception):
    pass


class StartupError(Exception):
    def __init__(self, exit_code: int, log_tail: str) -> None:
        self.exit_code = exit_code
        self.log_tail = log_tail
        super().__init__(f"exited immediately with code {exit_code}")


def find_pid_on_port(port: int) -> Optional[int]:
    """Find and return the PID of whatever process is listening on this TCP port, or None.

    Uses `ss` from iproute2. The output looks like:
        State  Recv-Q  Send-Q  Local Address:Port  ...  Process
        LISTEN 0       128     0.0.0.0:8000        ...  users:(("uvicorn",pid=1234,...))

    We parse the `pid=N` field from the Process column.
    Returns None if nothing is listening on that port or `ss` isn't available.
    """
    if not shutil.which("ss"):
        return None
    try:
        ss_output = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
        for line in ss_output.splitlines()[1:]:
            if f":{port}" in line:
                pid_match = re.search(r"pid=(\d+)", line)
                if pid_match:
                    return int(pid_match.group(1))
    except subprocess.TimeoutExpired:
        pass
    return None


def find_proc_on_port(port: int) -> Optional[Process]:
    listening_pid = find_pid_on_port(port)
    if listening_pid is None:
        return None
    for proc in Process.load_all().values():
        if proc.pid == listening_pid or listening_pid in _find_group_members(proc.pgid):
            return proc
    return None


def _find_group_members(pgid: int) -> list[int]:
    member_pids = []
    for stat_path in glob.glob("/proc/[0-9]*/stat"):
        try:
            fields = open(stat_path).read().split()
            if len(fields) >= 5 and int(fields[4]) == pgid:
                member_pids.append(int(fields[0]))
        except (OSError, ValueError):
            pass
    return member_pids


def _write_log_header(log_file: Path, full_cmd: list[str]) -> None:
    separator = "─" * 64
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as log_fh:
        log_fh.write(f"\n{separator}\n")
        log_fh.write(f"[sualw]  started  {timestamp}\n")
        log_fh.write(f"[sualw]  {' '.join(full_cmd)}\n")
        log_fh.write(f"{separator}\n\n")


def _read_log_tail(log_file: Path, num_lines: int = 20) -> str:
    """Return the last num_lines lines of the most recent session only.

    When a process is restarted, the log file accumulates output from
    multiple runs. For startup error messages we only want the current run,
    so we find the last '[sualw]  started' marker, skip past the header block,
    and return what follows.

    If the file doesn't exist yet (process crashed before writing anything),
    returns an empty string.
    """
    if not log_file.exists():
        return ""
    all_lines = log_file.read_text(errors="replace").splitlines()

    # Find the line index of the last '[sualw]  started' marker.
    last_header_line = None
    for i, line in enumerate(all_lines):
        if line.startswith("[sualw]  started"):
            last_header_line = i

    if last_header_line is not None:
        # Skip forward past the closing separator line (────────...).
        for i in range(last_header_line, min(last_header_line + 5, len(all_lines))):
            if all_lines[i].startswith("─" * 10):
                all_lines = all_lines[i + 1 :]
                # Strip the blank line that follows the header.
                if all_lines and all_lines[0].strip() == "":
                    all_lines = all_lines[1:]
                break

    return "\n".join(all_lines[-num_lines:])


class Process:
    def __init__(
        self,
        name: str,
        pid: int,
        pgid: int,
        command: list[str],
        log: str,
        started_at: str,
        exit_code: Optional[int] = None,
    ) -> None:
        self.name = name
        self.pid = pid
        self.pgid = pgid
        self.command = command
        self.log = log
        self.started_at = started_at
        self.exit_code = exit_code

    def to_json(self) -> dict:
        """Convert this Process to a plain dict for storage in registry.json."""
        return {
            "pid": self.pid,
            "pgid": self.pgid,
            "command": self.command,
            "log": self.log,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_json(cls, name: str, json_obj: dict) -> "Process":

        return cls(
            name=name,
            pid=json_obj["pid"],
            pgid=json_obj["pgid"],
            command=json_obj["command"],
            log=json_obj["log"],
            started_at=json_obj["started_at"],
            exit_code=json_obj.get("exit_code"),
        )

    @classmethod
    def load(cls, name: str) -> Optional["Process"]:
        json_obj = registry.load_entry(name)
        return cls.from_json(name, json_obj) if json_obj else None

    @classmethod
    def load_all(cls) -> dict[str, "Process"]:
        return {
            name: cls.from_json(name, json_obj)
            for name, json_obj in registry.load_all_entries().items()
        }

    @property
    def log_path(self) -> Path:
        return Path(self.log)

    @property
    def alive(self) -> bool:
        try:
            with open(f"/proc/{self.pid}/status") as status_file:
                for line in status_file:
                    if line.startswith("State:"):
                        state_char = line.split()[1]
                        return state_char != "Z"
            return False
        except FileNotFoundError:
            return False
        except OSError:
            return True

    @property
    def uptime_seconds(self) -> float:
        """
        How many seconds have passed since this process was sualwd.

        Parses started_at (ISO-8601 string from the registry) and subtracts
        from the current time. Returns 0.0 if the timestamp can't be parsed,
        so callers don't have to handle an error case.
        """
        try:
            start_time = datetime.fromisoformat(self.started_at).replace(
                tzinfo=timezone.utc
            )
            return (datetime.now(tz=timezone.utc) - start_time).total_seconds()
        except ValueError:
            return 0.0

    @property
    def uptime(self) -> str:
        """
        Human-readable uptime: '34s', '5m 12s', '2h 7m'.

        Derived from uptime_seconds. Used in `sualw list` and `sualw status`.
        """
        total_secs = int(self.uptime_seconds)
        if total_secs < 60:
            return f"{total_secs}s"
        if total_secs < 3600:
            return f"{total_secs // 60}m {total_secs % 60}s"
        return f"{total_secs // 3600}h {(total_secs % 3600) // 60}m"

    @property
    def ports(self) -> list[int]:
        """
        `TCP ports` any process in this group is currently listening on.

        We search the entire process group (PGID) rather than just self.pid
        because the actual server binary is a CHILD of the supervisor. The
        supervisor holds self.pid but the child (uvicorn, flask, etc.) is the
        one that opens the port. Both share self.pgid.

        Uses `ss` from iproute2, standard on all modern Linux systems.
        Returns an empty list if `ss` isn't available or times out.
        """
        if not shutil.which("ss"):
            return []
        # Get every PID in our process group to match against `ss` output.
        group_member_pids = set(_find_group_members(self.pgid))
        if not group_member_pids:
            return []
        listening_ports = []
        try:
            ss_output = subprocess.run(
                ["ss", "-tlnp"],  # TCP, listening, numeric, with process info
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout
            for line in ss_output.splitlines()[1:]:  # skip the header line
                pid_match = re.search(r"pid=(\d+)", line)
                port_match = re.search(r":(\d+)\s", line)
                if pid_match and port_match:
                    if int(pid_match.group(1)) in group_member_pids:
                        listening_ports.append(int(port_match.group(1)))
        except subprocess.TimeoutExpired:
            pass
        return listening_ports

    def stop(self, *, force: bool = False) -> bool:
        """Send SIGTERM (or SIGKILL if force=True) to the whole process group.

        We kill the PGID, not just self.pid. tools like
        `uvicorn --reload`, and `celery` spawn child worker processes.
        `os.killpg()` sends the signal to every PID in the group at once
        supervisor + command + all workers - in a single call.

        After signalling (or confirming it was already dead), the registry
        entry is removed so `sualw list` no longer shows it.

        Returns True if a signal was actually delivered, False if the process
        was already dead (useful so cli.py can show the right message).
        """
        sig = signal.SIGKILL if force else signal.SIGTERM
        signal_sent = False

        try:
            os.killpg(self.pgid, sig)
            signal_sent = True
        except ProcessLookupError:
            # The process group is already gone — that's fine.
            pass
        except PermissionError:
            # We don't have permission to signal this process. Propagate.
            raise

        # Belt-and-suspenders: if the group was gone but the root PID somehow
        # still exists, signal it directly.
        if not signal_sent:
            try:
                os.kill(self.pid, sig)
                signal_sent = True
            except ProcessLookupError:
                pass

        registry.delete_entry(self.name)
        return signal_sent

    def restart(self) -> "Process":
        """
        Stop this process and immediately re-launch it with the same command.

        Saves the command before calling stop() because stop() removes the
        registry entry — after that, self.command would still be set on this
        Python object (we're in memory) but the registry would be empty.
        Then starts fresh and returns the new Process.
        """
        saved_command = self.command  # save before stop() removes the entry
        self.stop(force=False)
        return Process.start(saved_command, self.name)

    # How long sualw waits after launching before deciding the process survived.
    # 0.8 seconds catches most immediate startup crashes (bad config, wrong
    # module name, port already in use) without making sualw feel slow.
    _STARTUP_GRACE_SECS = 0.8

    @classmethod
    def start(cls, command: list[str], name: str) -> "Process":
        bin_path = shutil.which(command[0])
        if bin_path is None:
            raise CommandNotFoundError(command[0])

        full_cmd = [bin_path] + command[1:]
        log_file = registry.get_log_path(name)
        registry.create_dirs()
        _write_log_header(log_file, full_cmd)

        supervisor_cmd = [
            sys.executable,
            "-m",
            "sualw.supervisor",
            name,
            "--",
            *full_cmd,
        ]

        supervisor_proc = subprocess.Popen(
            supervisor_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        pgid = os.getpgid(supervisor_proc.pid)
        new_proc = cls(
            name=name,
            pid=supervisor_proc.pid,
            pgid=pgid,
            command=full_cmd,
            log=str(log_file),
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        registry.save_entry(name, new_proc.to_json())

        time.sleep(cls._STARTUP_GRACE_SECS)

        if not new_proc.alive:
            # Re-read from registry — the supervisor may have written the
            # exit code during our sleep.
            refreshed = cls.load(name)
            recorded_exit_code = (
                refreshed.exit_code
                if refreshed and refreshed.exit_code is not None
                else -1
            )
            registry.delete_entry(name)
            raise StartupError(recorded_exit_code, _read_log_tail(log_file))

        # Return from registry so exit_code reflects what supervisor wrote.
        return cls.load(name) or new_proc

    def __repr__(self) -> str:
        state = "alive" if self.alive else f"exited({self.exit_code})"
        return f"Process(name={self.name!r}, pid={self.pid}, {state})"
