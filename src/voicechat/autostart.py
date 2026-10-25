"""`voicechat autostart`: run the app as a macOS login item.

A LaunchAgent in ~/Library/LaunchAgents starts `voicechat app` when you log in, with no terminal
involved, and starts it again if it ever crashes (not after you quit it on purpose). Permissions
are then attributed to the Python running voicechat rather than to a terminal, so macOS asks for
them once more the first time.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path

from voicechat.config import HOME_DIR, ensure_home
from voicechat.install import executable

LABEL = "com.voicechat.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
APP_LOG = HOME_DIR / "app.log"


def program() -> list[str]:
    exe = executable()
    if exe:
        return [exe]
    import sys

    return [sys.executable, "-m", "voicechat"]


def plist(extra_args: list[str] | tuple[str, ...] = ()) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [*program(), "app", *extra_args],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},  # back after a crash; not after Quit
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(APP_LOG),
        "StandardErrorPath": str(APP_LOG),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def enable(extra_args: list[str] | tuple[str, ...] = ()) -> Path:
    """Write the LaunchAgent and load it, which also starts the app now."""
    ensure_home()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as fh:
        plistlib.dump(plist(extra_args), fh)
    _launchctl("bootout", f"{_domain()}/{LABEL}")  # a previous version, if any; fine when there is none
    result = _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    if result.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {result.stderr.strip() or result.stdout.strip()}")
    return PLIST_PATH


def disable() -> bool:
    """Unload (which stops the app) and remove the LaunchAgent. False when there was none."""
    existed = PLIST_PATH.exists()
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if existed:
        PLIST_PATH.unlink()
    return existed


def status() -> dict:
    """{'installed': bool, 'loaded': bool, 'pid': int | None, 'state': str | None}"""
    info = {"installed": PLIST_PATH.exists(), "loaded": False, "pid": None, "state": None}
    result = _launchctl("print", f"{_domain()}/{LABEL}")
    if result.returncode == 0:
        info["loaded"] = True
        pid = re.search(r"^\s*pid = (\d+)", result.stdout, re.M)
        state = re.search(r"^\s*state = (\w+)", result.stdout, re.M)
        info["pid"] = int(pid.group(1)) if pid else None
        info["state"] = state.group(1) if state else None
    return info
