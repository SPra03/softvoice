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


def interpret(payload: dict[str, Any], speak_notifications: list[str], interrupt_on_prompt: bool,
              whole_turn: bool = True, interim_min_chars: int = 200) -> Action:
    event = payload.get("hook_event_name") or payload.get("type") or ""
    meta = {
        "event": event,
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "project": Path(payload["cwd"]).name if payload.get("cwd") else None,
    }

    if event == "Stop" or event == "agent-turn-complete":
        text = (payload.get("last_assistant_message") or payload.get("last-assistant-message") or "").strip()
        path = Path(payload["transcript_path"]).expanduser() if payload.get("transcript_path") else None
        if path and whole_turn:
            # The final block is often a short recap after a tool call; the substance came before it.
            blocks = turn_texts_from_transcript(path)
            if not text and blocks:
                text = blocks[-1].strip()
                blocks = blocks[:-1]
            earlier = [b.strip() for b in blocks if len(b.strip()) >= interim_min_chars and b.strip() != text]
            if earlier:
                text = "\n\n".join(earlier + ([text] if text else []))
        elif not text and path:
            text = last_assistant_text_from_transcript(path)
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


def _is_human_message(entry: dict[str, Any]) -> bool:
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def turn_texts_from_transcript(path: Path, tail_bytes: int = 4_000_000) -> list[str]:
    """Every assistant text block since the last human message, in order (tool calls are not text)."""
    if not path.exists():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = data.split("\n")
    if size > tail_bytes and lines:
        lines = lines[1:]  # the first line of a tail is usually cut in half
    texts: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_human_message(entry):
            texts = []
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    texts.append(block["text"])
    return texts
