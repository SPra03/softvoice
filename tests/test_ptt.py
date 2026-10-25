from softvoice.ptt import is_cancel, target_allowed

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
    from softvoice.ptt import is_tap

    assert is_tap(0.12, 350)
    assert not is_tap(0.6, 350)


def test_strip_send_word():
    from softvoice.ptt import strip_send_word

    words = ["send it", "send"]
    assert strip_send_word("Fix the login bug and add a test. Send it.", words) == ("Fix the login bug and add a test.", True)
    assert strip_send_word("fix the bug, send it", words) == ("fix the bug.", True)
    assert strip_send_word("Send it!", words) == ("", True)
    assert strip_send_word("Please resend the email.", words) == ("Please resend the email.", False)
    assert strip_send_word("Send the email to Bob.", words) == ("Send the email to Bob.", False)


def test_resolve_key_names():
    from softvoice.hotkey import resolve_key

    assert resolve_key("alt_r").keycode == 61
    assert (resolve_key("F5").keycode, resolve_key("F5").flag) == (96, None)
    import pytest
    with pytest.raises(SystemExit):
        resolve_key("banana")


def test_front_tracker_ignores_our_own_process():
    import os

    from softvoice.front import FrontTracker

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


def test_dictation_keys_swallow_return_and_escape_only():
    import Quartz

    from softvoice.hotkey import KEY_ESCAPE, KEY_RETURN, DictationKeys

    hits = []
    keys = DictationKeys(on_accept=lambda: hits.append("accept"), on_cancel=lambda: hits.append("cancel"))

    def key(code, flags=0):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, True)
        Quartz.CGEventSetFlags(ev, flags)
        return ev

    assert keys._callback(None, Quartz.kCGEventKeyDown, key(KEY_RETURN), None) is None
    assert keys._callback(None, Quartz.kCGEventKeyDown, key(KEY_ESCAPE), None) is None
    assert hits == ["accept", "cancel"]
    letter = key(0)  # 'a'
    assert keys._callback(None, Quartz.kCGEventKeyDown, letter, None) is letter
    combo = key(KEY_RETURN, Quartz.kCGEventFlagMaskCommand)
    assert keys._callback(None, Quartz.kCGEventKeyDown, combo, None) is combo  # Cmd+Return is the app's
    assert hits == ["accept", "cancel"]


def test_front_pid_never_reports_loginwindow(monkeypatch):
    from softvoice import front

    class FakeApp:
        def processIdentifier(self):
            return 1059

        def bundleIdentifier(self):
            return "com.apple.loginwindow"

    monkeypatch.setattr(front, "workspace_front_app", lambda: FakeApp())
    monkeypatch.setattr(front, "topmost_window_pid", lambda: 4242)
    assert front.front_pid() == 4242
    tracker = front.FrontTracker()
    tracker.note(FakeApp())
    assert tracker.pid is None  # loginwindow is never "the app you were in"


def test_talk_key_combination_is_pressed_released_and_swallowed():
    import Quartz

    from softvoice.hotkey import Hotkey, resolve_key

    b = resolve_key("alt+space")
    assert (b.keycode, b.mods, b.combo) == (49, Quartz.kCGEventFlagMaskAlternate, True)
    assert resolve_key("ctrl+shift+d").mods == Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskShift
    assert resolve_key("alt_r").combo is False and resolve_key("f5").combo is False
    hits = []
    hk = Hotkey(b, on_press=lambda: hits.append("down"), on_release=lambda: hits.append("up"))

    def key(code, down, flags=0):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(ev, flags)
        return ev

    plain = key(49, True)
    assert hk._callback(None, Quartz.kCGEventKeyDown, plain, None) is plain  # a space is a space
    assert hk._callback(None, Quartz.kCGEventKeyDown, key(49, True, Quartz.kCGEventFlagMaskAlternate), None) is None
    assert hk._callback(None, Quartz.kCGEventKeyUp, key(49, False), None) is None
    assert hits == ["down", "up"]
    cmd = key(49, True, Quartz.kCGEventFlagMaskCommand)
    assert hk._callback(None, Quartz.kCGEventKeyDown, cmd, None) is cmd  # cmd+space stays Spotlight's
    assert hits == ["down", "up"]
