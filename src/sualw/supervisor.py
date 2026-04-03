from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]

    # Parse: <name> -- <command token> <command token> ...
    try:
        separator_index = args.index("--")
        proc_name = args[0]
        proc_command = args[separator_index + 1 :]
    except (ValueError, IndexError):
        sys.stderr.write("sualw._supervisor: malformed arguments\n")
        sys.exit(127)

    if not proc_command:
        sys.stderr.write("sualw._supervisor: empty command\n")
        sys.exit(127)

    proc_log_file = Path.home() / ".sualw" / "logs" / f"{proc_name}.log"

    try:
        devnull_fd = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):  # stdin, stdout, stderr
            os.dup2(devnull_fd, fd)
        os.close(devnull_fd)
    except OSError:
        pass

    try:
        with open(proc_log_file, "a") as log_handle:
            child_proc = subprocess.Popen(
                proc_command,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        proc_exit_code = child_proc.wait()  # blocks until the command finishes
    except FileNotFoundError:
        proc_exit_code = 127  # standard code for "command not found"
    except Exception:
        proc_exit_code = 1

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(proc_log_file, "a") as log_handle:
            log_handle.write(f"\n[sualw]  exited({proc_exit_code})  {timestamp}\n")
    except OSError:
        pass
    try:
        from sualw import registry

        registry.save_exit_code(proc_name, proc_exit_code)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
