"""One `softvoice app` at a time.

The running app holds a lock on ~/.softvoice/app.pid (released by the kernel when it exits, so a
crash never leaves a stale lock). A second `softvoice app` sees the lock, asks the first one to
show its pill with a signal, and exits.
"""

from __future__ import annotations

import fcntl
import os
import signal
import time

from softvoice.config import HOME_DIR, ensure_home

APP_PID_PATH = HOME_DIR / "app.pid"
SHOW_SIGNAL = signal.SIGUSR1  # "show your pill"
_lock_fd: int | None = None


def claim() -> int | None:
    """Take the app lock. None when it is ours; otherwise the pid of the app that has it (0 if unreadable)."""
    global _lock_fd
    ensure_home()
    fd = os.open(APP_PID_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        pid = _read_pid(fd)
        os.close(fd)
        return pid
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _lock_fd = fd
    return None


def release() -> None:
    global _lock_fd
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)  # closing drops the lock
        except OSError:
            pass
        _lock_fd = None


def running_pid() -> int | None:
    """The pid of a running app, without taking the lock ourselves."""
    try:
        fd = os.open(APP_PID_PATH, os.O_RDWR)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return _read_pid(fd) or None
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def show(pid: int) -> bool:
    try:
        os.kill(pid, SHOW_SIGNAL)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def quit(pid: int, timeout_s: float = 8.0) -> bool:
    """Ask a running app to quit (it saves the pill position) and wait for it to go."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def _read_pid(fd: int) -> int:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        return int(os.read(fd, 32).decode().strip() or 0)
    except (OSError, ValueError):
        return 0
