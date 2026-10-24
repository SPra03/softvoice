"""Interpret hook payloads from Claude Code and Codex.

Both agents send one JSON object on stdin. Claude Code's Stop and Codex's Stop carry
`last_assistant_message`; Claude Code's Notification carries `message` and
`notification_type`; both send UserPromptSubmit when you send a prompt. Codex's older
`notify` setting passes `{"type": "agent-turn-complete", "last-assistant-message": ...}`
as a command-line argument instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Action:
    kind: str  # "speak" | "stop" | "ignore"
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def interpret(payload: dict[str, Any], speak_notifications: list[str], interrupt_on_prompt: bool) -> Action:
    event = payload.get("hook_event_name") or payload.get("type") or ""
    meta = {
        "event": event,
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "project": Path(payload["cwd"]).name if payload.get("cwd") else None,
    }

    if event == "Stop" or event == "agent-turn-complete":
        text = payload.get("last_assistant_message") or payload.get("last-assistant-message")
        if not text and payload.get("transcript_path"):
            text = last_assistant_text_from_transcript(Path(payload["transcript_path"]).expanduser())
        if not text:
            return Action("ignore", meta=meta)
        return Action("speak", text=text, meta=meta)

    if event == "Notification":
        kind = payload.get("notification_type") or ""
        if kind in speak_notifications and payload.get("message"):
            meta["notification_type"] = kind
            return Action("speak", text=str(payload["message"]), meta=meta | {"priority": True})
        return Action("ignore", meta=meta)

    if event == "UserPromptSubmit":
        return Action("stop" if interrupt_on_prompt else "ignore", meta=meta)

    return Action("ignore", meta=meta)


def last_assistant_text_from_transcript(path: Path) -> str:
    """Fallback for older agents: read the final assistant text blocks from a JSONL transcript."""
    if not path.exists():
        return ""
    last = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                content = (entry.get("message") or {}).get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "\n".join(
                        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
                    )
                else:
                    continue
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last
