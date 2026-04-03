from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

SUALW_HOME = Path.home() / ".sualw"
LOG_DIR = SUALW_HOME / "logs"
REGISTRY_FILE = SUALW_HOME / "registry.json"
LOCK_FILE = SUALW_HOME / ".lock"


def create_dirs() -> None:
    SUALW_HOME.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


@contextmanager
def _registry_lock() -> Iterator[None]:
    create_dirs()
    with open(LOCK_FILE, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _load_json() -> dict:
    create_dirs()
    if not REGISTRY_FILE.exists():
        return {}
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(registry_dict: dict) -> None:
    create_dirs()
    fd, tmp_path = tempfile.mkstemp(dir=SUALW_HOME, prefix=".reg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmp_fh:
            json.dump(registry_dict, tmp_fh, indent=2, default=str)
            tmp_fh.flush()
            os.fsync(tmp_fh.fileno())
        os.replace(tmp_path, REGISTRY_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_all_entries() -> dict[str, dict]:
    """Return every entry in the registry as a plain dict keyed by process name.

    Used by `sualw list` and any operation that needs to iterate all processes.
    Each value is the raw JSON object for that process `proc.py` converts
    these into Process instances.
    """
    return _load_json()


def load_entry(name: str) -> Optional[dict]:
    """
    Return the raw JSON object for one process by name, or None if not found.

    Used by `sualw toggle uvicorn`, `sualw stop uvicorn`, etc. where the user
    targets a specific process by the name they gave it (or its binary name).
    """
    return _load_json().get(name)


def save_entry(name: str, entry_dict: dict) -> None:
    """Insert or replace one process entry in the registry.

    Takes the exclusive lock, reads the current registry, updates the
    named entry, and writes back atomically. This is the only correct
    way to add a new process — do not call _save_json directly.
    """
    with _registry_lock():
        registry_dict = _load_json()
        registry_dict[name] = entry_dict
        _save_json(registry_dict)


def delete_entry(name: str) -> bool:
    with _registry_lock():
        registry_dict = _load_json()
        if name not in registry_dict:
            return False
        del registry_dict[name]
        _save_json(registry_dict)
        return True


def save_exit_code(name: str, exit_code: int) -> None:
    """Write the exit code for a process back into its registry entry."""
    with _registry_lock():
        registry_dict = _load_json()
        if name in registry_dict:
            registry_dict[name]["exit_code"] = exit_code
            _save_json(registry_dict)


def get_log_path(name: str) -> Path:
    return LOG_DIR / f"{name}.log"
