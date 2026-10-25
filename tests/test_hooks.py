import json

from softvoice.hooks import interpret, last_assistant_text_from_transcript

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


def test_whole_turn_speaks_substance_before_tool_calls(tmp_path):
    long_block = "Here is the design proposal. " * 12  # ~350 chars of substance before a tool call
    rows = [
        {"type": "user", "message": {"content": "earlier question"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Old answer that must not be spoken."}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "what should we build?"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Starting the build."}]}},  # short progress note
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": long_block}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "wrap_up", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
    ]
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in rows))
    a = interpret({"hook_event_name": "Stop", "transcript_path": str(t), "last_assistant_message": "In short: build it."}, NOTIFY, True)
    assert a.kind == "speak"
    assert a.text.startswith(long_block.strip())
    assert a.text.endswith("In short: build it.")
    assert "Starting the build." not in a.text
    assert "Old answer" not in a.text
    # whole-turn off: only the final block
    b = interpret({"hook_event_name": "Stop", "transcript_path": str(t), "last_assistant_message": "In short: build it."}, NOTIFY, True, whole_turn=False)
    assert b.text == "In short: build it."


def test_split_sentences_merges_short_ones():
    from softvoice.daemon import split_sentences

    text = "Yes. That is possible, and I would do it in two layers. Here is why! Short? Done."
    out = split_sentences(text)
    assert out[0].startswith("Yes. That is possible")
    assert out[-1] == "Here is why! Short? Done."  # short sentences ride along
    assert " ".join(out) == text
