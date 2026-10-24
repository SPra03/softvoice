"""Talk to the daemon; start it if it isn't running. Imports nothing heavy."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any

from voicechat.config import LOG_PATH, SOCKET_PATH, ensure_home


class DaemonUnavailable(RuntimeError):
    pass


def _request(req: dict[str, Any], timeout: float) -> dict[str, Any]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCKET_PATH))
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            part = s.recv(65536)
            if not part:
                break
            buf += part
        return json.loads(buf or b"{}")
    finally:
        s.close()


def alive(timeout: float = 0.5) -> bool:
    try:
        return _request({"cmd": "status"}, timeout).get("ok", False)
    except (OSError, ValueError):
        return False


def spawn_daemon() -> None:
    ensure_home()
    log = open(LOG_PATH, "ab")
    subprocess.Popen(
        [sys.executable, "-m", "voicechat", "serve"],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def ensure_daemon(wait: float = 180.0) -> bool:
    """Return True once the daemon answers. Spawns it when needed and waits for the model."""
    if alive():
        return True
    spawn_daemon()
    deadline = time.monotonic() + wait
    delay = 0.1
    while time.monotonic() < deadline:
        time.sleep(delay)
        delay = min(delay * 1.5, 1.0)
        if alive():
            return True
    return False


def send(req: dict[str, Any], autostart: bool = True, timeout: float = 5.0, wait: float = 180.0) -> dict[str, Any]:
    try:
        return _request(req, timeout)
    except (OSError, ValueError):
        if not autostart or not ensure_daemon(wait):
            raise DaemonUnavailable("voicechat daemon is not running (start it with: voicechat serve)")
        return _request(req, timeout)


def subscribe(connect_timeout: float = 5.0):
    """Yield daemon events (speech_start, speech_end, daemon_quit) until the daemon goes away."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(connect_timeout)
    s.connect(str(SOCKET_PATH))
    s.sendall(b'{"cmd": "subscribe"}\n')
    s.settimeout(None)
    reader = s.makefile("r", encoding="utf-8")
    try:
        for line in reader:
            line = line.strip()
            if line:
                yield json.loads(line)
    finally:
        reader.close()
        s.close()
