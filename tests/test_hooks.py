import json

from voicechat.hooks import interpret, last_assistant_text_from_transcript

NOTIFY = ["permission_prompt"]


def test_claude_stop_speaks_last_message():
    a = interpret({"hook_event_name": "Stop", "last_assistant_message": "Done.", "cwd": "/x/myproj", "session_id": "s1"}, NOTIFY, True)
    assert a.kind == "speak" and a.text == "Done." and a.meta["project"] == "myproj"


def test_stop_without_text_is_ignored():
    assert interpret({"hook_event_name": "Stop"}, NOTIFY, True).kind == "ignore"


def test_codex_notify_payload():
    a = interpret({"type": "agent-turn-complete", "last-assistant-message": "Built it."}, NOTIFY, True)
    assert a.kind == "speak" and a.text == "Built it."


def test_notification_filtering():
    base = {"hook_event_name": "Notification", "message": "Claude needs your permission"}
    assert interpret(base | {"notification_type": "permission_prompt"}, NOTIFY, True).kind == "speak"
    assert interpret(base | {"notification_type": "idle_prompt"}, NOTIFY, True).kind == "ignore"


def test_prompt_submit_stops_speech_when_enabled():
    assert interpret({"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, NOTIFY, True).kind == "stop"
    assert interpret({"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, NOTIFY, False).kind == "ignore"


def test_transcript_fallback(tmp_path):
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "First."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Last."}]}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows))
    assert last_assistant_text_from_transcript(t) == "Last."
    a = interpret({"hook_event_name": "Stop", "transcript_path": str(t)}, NOTIFY, True)
    assert a.kind == "speak" and a.text == "Last."
