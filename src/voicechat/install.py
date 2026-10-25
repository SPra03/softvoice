"""Register voicechat's hooks with Claude Code and Codex."""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CODEX_DIR = Path.home() / ".codex"
CODEX_HOOKS = CODEX_DIR / "hooks.json"
EVENTS = ("Stop", "Notification", "UserPromptSubmit")
MARK = "voicechat hook"


def executable() -> str | None:
    """The `voicechat` command to call back into: the one running now, else the one on PATH."""
    exe = shutil.which("voicechat")
    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if argv0 and argv0.name == "voicechat" and argv0.exists():
        exe = str(argv0)
    return exe


def hook_command() -> str:
    exe = executable()
    if not exe:
        return f"{sys.executable} -m voicechat hook"
    return f"{exe} hook"


def _entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command, "async": True}]}


def _strip_ours(groups: list) -> list:
    kept = []
    for group in groups:
        hooks = [h for h in group.get("hooks", []) if MARK not in str(h.get("command", ""))]
        if hooks:
            kept.append({**group, "hooks": hooks})
    return kept


def _merge(settings: dict, command: str | None) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        groups = _strip_ours(hooks.get(event, []))
        if command:
            groups.append(_entry(command))
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    return settings


def _write_json(path: Path, data: dict) -> Path | None:
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return backup


def install_claude(command: str) -> tuple[Path, Path | None]:
    settings = json.loads(CLAUDE_SETTINGS.read_text()) if CLAUDE_SETTINGS.exists() else {}
    backup = _write_json(CLAUDE_SETTINGS, _merge(settings, command))
    return CLAUDE_SETTINGS, backup


def uninstall_claude() -> Path | None:
    if not CLAUDE_SETTINGS.exists():
        return None
    settings = json.loads(CLAUDE_SETTINGS.read_text())
    _write_json(CLAUDE_SETTINGS, _merge(settings, None))
    return CLAUDE_SETTINGS


def codex_snippet(command: str) -> dict:
    return {"hooks": {event: [_entry(command)] for event in ("Stop", "UserPromptSubmit")}}


def install_codex(command: str) -> tuple[Path, Path | None] | None:
    if not CODEX_DIR.exists():
        return None
    data = json.loads(CODEX_HOOKS.read_text()) if CODEX_HOOKS.exists() else {}
    hooks = data.setdefault("hooks", {})
    for event in ("Stop", "UserPromptSubmit"):
        groups = _strip_ours(hooks.get(event, []))
        groups.append(_entry(command))
        hooks[event] = groups
    backup = _write_json(CODEX_HOOKS, data)
    return CODEX_HOOKS, backup


def uninstall_codex() -> Path | None:
    if not CODEX_HOOKS.exists():
        return None
    data = json.loads(CODEX_HOOKS.read_text())
    hooks = data.get("hooks", {})
    for event in list(hooks):
        groups = _strip_ours(hooks[event])
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    _write_json(CODEX_HOOKS, data)
    return CODEX_HOOKS
