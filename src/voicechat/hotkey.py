"""The talk key and synthetic keystrokes, straight on Quartz.

An event tap on the main run loop reports presses and releases of the talk key: a single key
(a modifier such as right Option, fn, or an F-key; listen-only, the app in front sees it too) or
a combination such as alt+space (an active tap, so the combination is swallowed and the app in
front never sees it). Pasting, copying and Enter are posted as keyboard events. No background
thread ever calls the text-input services, which macOS 26 traps on inside a GUI app.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import Quartz

# keycodes of the keys you can bind; modifiers arrive as flagsChanged events
MODIFIERS = {
    "alt_r": (61, Quartz.kCGEventFlagMaskAlternate), "alt_l": (58, Quartz.kCGEventFlagMaskAlternate),
    "alt": (58, Quartz.kCGEventFlagMaskAlternate),
    "cmd_r": (54, Quartz.kCGEventFlagMaskCommand), "cmd_l": (55, Quartz.kCGEventFlagMaskCommand),
    "cmd": (55, Quartz.kCGEventFlagMaskCommand),
    "ctrl_r": (62, Quartz.kCGEventFlagMaskControl), "ctrl_l": (59, Quartz.kCGEventFlagMaskControl),
    "ctrl": (59, Quartz.kCGEventFlagMaskControl),
    "shift_r": (60, Quartz.kCGEventFlagMaskShift), "shift_l": (56, Quartz.kCGEventFlagMaskShift),
    "shift": (56, Quartz.kCGEventFlagMaskShift),
    "fn": (63, Quartz.kCGEventFlagMaskSecondaryFn),
}
PLAIN_KEYS = {
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
    "f10": 109, "f11": 103, "f12": 111, "f13": 105, "f14": 107, "f15": 113, "f16": 106,
    "f17": 64, "f18": 79, "f19": 80, "f20": 90,
}
KEY_V, KEY_C, KEY_RETURN = 9, 8, 36
KEY_ENTER_PAD, KEY_ESCAPE = 76, 53
_COMBO_MODS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskAlternate
ALL_MODS = _COMBO_MODS | Quartz.kCGEventFlagMaskShift | Quartz.kCGEventFlagMaskSecondaryFn

# the modifiers of a combination, and the key it ends with (US layout keycodes)
MOD_FLAGS = {
    "alt": Quartz.kCGEventFlagMaskAlternate, "option": Quartz.kCGEventFlagMaskAlternate, "opt": Quartz.kCGEventFlagMaskAlternate,
    "cmd": Quartz.kCGEventFlagMaskCommand, "command": Quartz.kCGEventFlagMaskCommand,
    "ctrl": Quartz.kCGEventFlagMaskControl, "control": Quartz.kCGEventFlagMaskControl,
    "shift": Quartz.kCGEventFlagMaskShift, "fn": Quartz.kCGEventFlagMaskSecondaryFn,
}
KEYS = {
    "space": 49, "tab": 48, "return": 36, "enter": 36, "escape": 53, "esc": 53, "delete": 51, "backspace": 51,
    "`": 50, "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42, ";": 41, "'": 39, ",": 43, ".": 47, "/": 44,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
    "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    **PLAIN_KEYS,
}


@dataclass(frozen=True)
class Binding:
    """What the talk key is: a modifier (flag set), a plain key (neither), or a combination (mods set)."""

    name: str
    keycode: int
    flag: int | None = None  # a modifier key: the flag that says it is down
    mods: int = 0  # a combination: the modifiers that must be held with keycode

    @property
    def combo(self) -> bool:
        return self.mods != 0


def resolve_key(name: str) -> Binding:
    """A Binding for a key name: alt_r, cmd_r, fn, f5, or a combination such as alt+space."""
    name = name.strip().lower()
    if name in MODIFIERS:
        keycode, flag = MODIFIERS[name]
        return Binding(name, keycode, flag=flag)
    if name in PLAIN_KEYS:
        return Binding(name, PLAIN_KEYS[name])
    parts = [p.strip() for p in name.split("+")]
    if len(parts) >= 2 and all(p in MOD_FLAGS for p in parts[:-1]) and parts[-1] in KEYS:
        mods = 0
        for p in parts[:-1]:
            mods |= MOD_FLAGS[p]
        return Binding(name, KEYS[parts[-1]], mods=mods)
    raise SystemExit(f"unknown hotkey {name!r}; use one of: {', '.join(list(MODIFIERS) + list(PLAIN_KEYS))}, "
                     f"or a combination such as alt+space, ctrl+shift+d")


class Hotkey:
    """Calls on_press / on_release for the talk key. `install` must run on the main thread."""

    def __init__(self, binding: Binding, on_press: Callable[[], None], on_release: Callable[[], None],
                 on_scroll: Callable[[], None] | None = None):
        self.binding = binding
        self.keycode = binding.keycode
        self.flag = binding.flag
        self.on_press = on_press
        self.on_release = on_release
        self.on_scroll = on_scroll  # any scroll wheel or trackpad scroll, anywhere; the underline follows the page
        self.down = False
        self.tap = None
        self.source = None

    def install(self) -> bool:
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp) | Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel))
        # A combination must be swallowed (alt+space would otherwise type a non-breaking space), which
        # takes an active tap; a single key is only listened to.
        option = Quartz.kCGEventTapOptionDefault if self.binding.combo else Quartz.kCGEventTapOptionListenOnly
        self.tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                           option, mask, self._callback, None)
        if self.tap is None:
            return False  # Input Monitoring not granted
        self.source = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        return True

    def remove(self) -> None:
        if self.tap is not None:
            Quartz.CGEventTapEnable(self.tap, False)
        if self.source is not None:
            Quartz.CFRunLoopRemoveSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        self.tap = self.source = None

    def _callback(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self.tap, True)
                return event
            if etype == Quartz.kCGEventScrollWheel:
                if self.on_scroll is not None:
                    self.on_scroll()
                return event
            if self.binding.combo:
                return self._combo(etype, event)
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode != self.keycode:
                return event
            if etype == Quartz.kCGEventFlagsChanged:
                pressed = bool(Quartz.CGEventGetFlags(event) & self.flag) if self.flag else False
            elif etype == Quartz.kCGEventKeyDown:
                if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                    return event
                pressed = True
            else:
                pressed = False
            if pressed and not self.down:
                self.down = True
                self.on_press()
            elif not pressed and self.down:
                self.down = False
                self.on_release()
        except Exception as exc:  # never let an error escape into the event system
            print(f"hotkey error: {type(exc).__name__}: {exc}", flush=True)
        return event

    def _combo(self, etype, event):
        """A combination: press on the key going down with exactly those modifiers, release on the
        key coming up (or the modifiers letting go first). Our events are swallowed."""
        held = Quartz.CGEventGetFlags(event) & ALL_MODS
        if etype == Quartz.kCGEventFlagsChanged:
            if self.down and (held & self.binding.mods) != self.binding.mods:
                self.down = False
                self.on_release()
            return event
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if keycode != self.keycode:
            return event
        if etype == Quartz.kCGEventKeyDown:
            if held != self.binding.mods:
                return event  # the same key with other modifiers is the app's
            if not self.down and not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                self.down = True
                self.on_press()
            return None  # swallowed, repeats included
        if etype == Quartz.kCGEventKeyUp and self.down:
            self.down = False
            self.on_release()
            return None
        return event


class DictationKeys:
    """While a dictation session is open, Return accepts it (✓) and Escape discards it (✕), and
    neither reaches the app in front. An active tap, so it can swallow those two keys; it is
    installed when the session opens and removed when it ends, so no other keystroke ever passes
    through us. `install` and `remove` must run on the main thread."""

    def __init__(self, on_accept: Callable[[], None], on_cancel: Callable[[], None]):
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self.tap = None
        self.source = None

    def install(self) -> bool:
        self.tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                           Quartz.kCGEventTapOptionDefault, Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
                                           self._callback, None)
        if self.tap is None:
            return False  # Input Monitoring not granted: the pill's buttons and the key still work
        self.source = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        return True

    def remove(self) -> None:
        if self.tap is not None:
            Quartz.CGEventTapEnable(self.tap, False)
        if self.source is not None:
            Quartz.CFRunLoopRemoveSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        self.tap = self.source = None

    def _callback(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self.tap, True)
                return event
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode not in (KEY_RETURN, KEY_ENTER_PAD, KEY_ESCAPE):
                return event
            if Quartz.CGEventGetFlags(event) & _COMBO_MODS:
                return event  # Cmd/Ctrl/Option combinations are the app's business
            if not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                (self.on_cancel if keycode == KEY_ESCAPE else self.on_accept)()
            return None  # swallowed: the app never sees this Return or Escape
        except Exception as exc:
            print(f"dictation keys error: {type(exc).__name__}: {exc}", flush=True)
            return event



def _post(keycode: int, down: bool, flags: int = 0) -> None:
    ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
    Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def press(keycode: int, cmd: bool = False) -> None:
    flags = Quartz.kCGEventFlagMaskCommand if cmd else 0
    _post(keycode, True, flags)
    _post(keycode, False, flags)


def run_main_loop_once(seconds: float = 0.25) -> None:
    """Service the main run loop for a while (the terminal UI's wait loop needs this for the tap)."""
    Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, seconds, False)
