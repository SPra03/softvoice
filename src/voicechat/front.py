"""Which app a paste lands in.

Normally that is the front app. But our own app can end up in front (showing the pill's menu
activates it, and macOS does not always let us hand activation back), and then a paste would go
nowhere. So we remember the last front app that is not us, and hand focus back to it first.
"""

from __future__ import annotations

import os
import time

import objc
from Foundation import NSObject


IGNORED_BUNDLES = {"com.apple.loginwindow"}  # what a launchd-started process is sometimes told is "front"


def front_pid() -> int | None:
    """The pid of the app in front, which may be us (callers check). NSWorkspace first; when it
    names nobody or loginwindow (which a process started by launchd is sometimes told), the owner
    of the topmost ordinary window instead."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None and app.bundleIdentifier() not in IGNORED_BUNDLES:
            return int(app.processIdentifier())
    except Exception:
        pass
    return topmost_window_pid()


def topmost_window_pid() -> int | None:
    """Owner of the first on-screen window at the normal level (front to back), other than us."""
    try:
        import Quartz

        for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
            pid = w.get("kCGWindowOwnerPID")
            if w.get("kCGWindowLayer") == 0 and pid and pid != os.getpid():
                return int(pid)
    except Exception:
        pass
    return None


class FrontTracker:
    """Remembers the last front app that is not this process. `install` must run on the main thread."""

    def __init__(self):
        self.pid: int | None = None
        self.bundle: str | None = None
        self.name: str | None = None
        self._observer = None

    def install(self) -> None:
        from AppKit import NSWorkspace, NSWorkspaceDidActivateApplicationNotification

        ws = NSWorkspace.sharedWorkspace()
        self.note(ws.frontmostApplication())
        self._observer = _Observer.alloc().initWithTracker_(self)
        ws.notificationCenter().addObserver_selector_name_object_(
            self._observer, b"activated:", NSWorkspaceDidActivateApplicationNotification, None)

    def note(self, app) -> None:
        """Record `app` (anything with processIdentifier/bundleIdentifier/localizedName) unless it is us."""
        if app is None:
            return
        try:
            pid = int(app.processIdentifier())
        except Exception:
            return
        if pid == os.getpid() or app.bundleIdentifier() in IGNORED_BUNDLES:
            return
        self.pid, self.bundle, self.name = pid, app.bundleIdentifier(), app.localizedName()


class _Observer(NSObject):
    def initWithTracker_(self, tracker):
        self = objc.super(_Observer, self).init()
        self.tracker = tracker
        return self

    def activated_(self, note):
        try:
            from AppKit import NSWorkspaceApplicationKey

            self.tracker.note(note.userInfo()[NSWorkspaceApplicationKey])
        except Exception:
            pass


def give_focus_to(pid: int | None, timeout_s: float = 0.8) -> bool:
    """Make `pid`'s app the active one and wait until it is. False when macOS would not let us."""
    if not pid:
        return False
    try:
        from AppKit import NSApplication, NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        nsapp = NSApplication.sharedApplication()
        if hasattr(nsapp, "yieldActivationToApplication_"):  # macOS 14+: cooperative activation
            try:
                nsapp.yieldActivationToApplication_(app)
            except Exception:
                pass
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception:
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if front_pid() == pid:
            return True
        time.sleep(0.02)
    return front_pid() == pid
