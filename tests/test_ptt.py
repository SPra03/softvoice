from voicechat.ptt import is_cancel, target_allowed

PATTERNS = ["com.apple.Terminal", "com.anthropic.claudefordesktop", "com.jetbrains.*"]


def test_target_allowed_by_pattern_or_last_ptt():
    assert target_allowed("com.apple.Terminal", PATTERNS, None)
    assert target_allowed("com.jetbrains.intellij", PATTERNS, None)
    assert not target_allowed("com.apple.Safari", PATTERNS, None)
    assert target_allowed("com.apple.Safari", PATTERNS, "com.apple.Safari")
    assert target_allowed(None, PATTERNS, None)  # unknown: trust the user


def test_cancel_words():
    words = ["cancel", "never mind", "scratch that"]
    assert is_cancel("Cancel.", words)
    assert is_cancel("never mind", words)
    assert is_cancel("Never, mind!", words)
    assert not is_cancel("cancel the deploy and roll back", words)
