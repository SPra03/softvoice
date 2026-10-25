"""macOS privacy permissions the listener needs.

The key watcher needs Input Monitoring; pasting needs Accessibility. Both are granted to the
app that owns the terminal (Terminal, iTerm, the Claude desktop app, ...), not to Python.
Asking through the system APIs shows the standard dialogs and adds that app to the lists.
"""

from __future__ import annotations

import ctypes

_LISTEN_EVENT = 1  # kIOHIDRequestTypeListenEvent


def _iokit():
    lib = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
    lib.IOHIDCheckAccess.restype = ctypes.c_uint32
    lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
    lib.IOHIDRequestAccess.restype = ctypes.c_bool
    lib.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
    return lib


def input_monitoring() -> str:
    """'granted', 'denied', 'unknown' (never asked) or 'unavailable'."""
    try:
        return {0: "granted", 1: "denied", 2: "unknown"}.get(_iokit().IOHIDCheckAccess(_LISTEN_EVENT), "unknown")
    except (OSError, AttributeError):
        return "unavailable"


def request_input_monitoring() -> bool:
    try:
        return bool(_iokit().IOHIDRequestAccess(_LISTEN_EVENT))
    except (OSError, AttributeError):
        return False


def accessibility(prompt: bool = False) -> bool | None:
    """True/False, or None when it cannot be determined. `prompt` shows the system dialog."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception:
        try:
            lib = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(lib.AXIsProcessTrusted())
        except Exception:
            return None


def check_and_request(need_paste: bool, need_hotkey: bool, out=print) -> bool:
    """Report both permissions, prompting for any that is missing. Returns True when all needed ones are granted."""
    ok = True
    if need_hotkey:
        status = input_monitoring()
        if status == "unknown":
            request_input_monitoring()
            status = input_monitoring()
        if status == "granted":
            out("Input Monitoring: granted (push-to-talk key)")
        elif status == "unavailable":
            out("Input Monitoring: could not check")
        else:
            ok = False
            out("Input Monitoring: NOT granted. The push-to-talk key will not work until you enable this terminal's app")
            out("  (Claude, Terminal, iTerm, ...) under System Settings > Privacy & Security > Input Monitoring.")
            out("  The key starts working as soon as you do. Hands-free listening works without it.")
    if need_paste:
        trusted = accessibility(prompt=False)
        if trusted is False:
            accessibility(prompt=True)  # system dialog with an "Open System Settings" button
            trusted = accessibility(prompt=False)
        if trusted:
            out("Accessibility: granted (pasting)")
        elif trusted is None:
            out("Accessibility: could not check")
        else:
            ok = False
            out("Accessibility: NOT granted. Transcripts cannot be pasted until you enable this terminal's app")
            out("  under System Settings > Privacy & Security > Accessibility (macOS just asked). No restart needed.")
    return ok
