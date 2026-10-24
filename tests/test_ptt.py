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


def test_tap_versus_hold():
    from voicechat.ptt import is_tap

    assert is_tap(0.12, 350)
    assert not is_tap(0.6, 350)


def test_strip_send_word():
    from voicechat.ptt import strip_send_word

    words = ["send it", "send"]
    assert strip_send_word("Fix the login bug and add a test. Send it.", words) == ("Fix the login bug and add a test.", True)
    assert strip_send_word("fix the bug, send it", words) == ("fix the bug.", True)
    assert strip_send_word("Send it!", words) == ("", True)
    assert strip_send_word("Please resend the email.", words) == ("Please resend the email.", False)
    assert strip_send_word("Send the email to Bob.", words) == ("Send the email to Bob.", False)


def test_resolve_key_names():
    from voicechat.hotkey import resolve_key

    assert resolve_key("alt_r")[0] == 61
    assert resolve_key("F5") == (96, None)
    import pytest
    with pytest.raises(SystemExit):
        resolve_key("banana")


def test_front_tracker_ignores_our_own_process():
    import os

    from voicechat.front import FrontTracker

    class App:
        def __init__(self, pid, bundle, name):
            self._pid, self._bundle, self._name = pid, bundle, name

        def processIdentifier(self):
            return self._pid

        def bundleIdentifier(self):
            return self._bundle

        def localizedName(self):
            return self._name

    t = FrontTracker()
    t.note(App(4242, "com.anthropic.claudefordesktop", "Claude"))
    t.note(App(os.getpid(), "org.python.python", "Python"))  # the pill's menu made us front
    assert (t.pid, t.bundle, t.name) == (4242, "com.anthropic.claudefordesktop", "Claude")
    t.note(None)
    assert t.pid == 4242
