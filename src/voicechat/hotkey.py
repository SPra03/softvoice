"""The hotkey and synthetic keystrokes, straight on Quartz.

A listen-only event tap on the main run loop reports presses and releases of one key by
keycode. Pasting, copying and Enter are posted as keyboard events. No background thread ever
calls the text-input services, which macOS 26 traps on inside a GUI app.
"""

from __future__ import annotations

import time
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


def resolve_key(name: str) -> tuple[int, int | None]:
    """(keycode, modifier flag or None) for a key name such as alt_r, cmd_r, ctrl_r, f5."""
    name = name.strip().lower()
    if name in MODIFIERS:
        return MODIFIERS[name]
    if name in PLAIN_KEYS:
        return PLAIN_KEYS[name], None
    raise SystemExit(f"unknown hotkey {name!r}; use one of: {', '.join(list(MODIFIERS) + list(PLAIN_KEYS))}")


class Hotkey:
    """Calls on_press / on_release for one key. `install` must run on the main thread."""

    def __init__(self, keycode: int, flag: int | None, on_press: Callable[[], None], on_release: Callable[[], None]):
        self.keycode = keycode
        self.flag = flag
        self.on_press = on_press
        self.on_release = on_release
        self.down = False
        self.tap = None
        self.source = None

    def install(self) -> bool:
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp))
        self.tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                           Quartz.kCGEventTapOptionListenOnly, mask, self._callback, None)
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
