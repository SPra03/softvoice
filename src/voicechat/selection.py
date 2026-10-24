"""Collapse the text selection in the front app once we have read it.

You select a paragraph and click play: we copy it, the voice reads it, the underline follows.
The blue selection stays until you click somewhere. So we ask the app to collapse it through
accessibility, two ways:

- native and editable text (Terminal, TextEdit, editors): the focused element's
  AXSelectedTextRange is set to an empty range at the selection's end
- web content (Chromium: Electron apps, VS Code, Cursor): the web area's
  AXSelectedTextMarkerRange is set to an empty range at the selection's end

Apps may accept the request and ignore it; the Claude desktop app does (its web contents take
no accessibility writes at all, selection or focus). We read the selection back afterwards and
say so, instead of claiming success. A real mouse click would clear it, but it also moves
keyboard focus out of the prompt, so the next paste would go nowhere; not worth it.
"""

from __future__ import annotations

import collections
import time


def _ax():
    import ApplicationServices as AS

    return AS


def _attr(AS, el, name):
    err, value = AS.AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def _param(AS, el, name, value):
    err, out = AS.AXUIElementCopyParameterizedAttributeValue(el, name, value, None)
    return out if err == 0 else None


def _settable(AS, el, name) -> bool:
    err, ok = AS.AXUIElementIsAttributeSettable(el, name, None)
    return err == 0 and bool(ok)


def _cfrange(AS, value):
    if value is None:
        return None
    try:
        err, rng = AS.AXValueGetValue(value, AS.kAXValueTypeCFRange, None)
        return (int(rng.location), int(rng.length)) if err else None
    except Exception:
        return None


def _web_area(AS, start, window, limit: int = 3000):
    """The AXWebArea above `start`, else the first one below `window`."""
    el = start
    for _ in range(40):
        if el is None:
            break
        if _attr(AS, el, "AXRole") == "AXWebArea":
            return el
        el = _attr(AS, el, "AXParent")
    if window is None:
        return None
    queue = collections.deque([window])
    seen = 0
    while queue and seen < limit:
        el = queue.popleft()
        seen += 1
        if _attr(AS, el, "AXRole") == "AXWebArea":
            return el
        queue.extend(_attr(AS, el, "AXChildren") or [])
    return None


def clear_selection(pid: int | None) -> str:
    """Collapse the selection in app `pid`. Returns what happened, for the log:
    "collapsed", "nothing selected", "ignored by the app", or "unsupported"."""
    if not pid:
        return "unsupported"
    AS = _ax()
    app = AS.AXUIElementCreateApplication(pid)
    AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    focused = _attr(AS, app, "AXFocusedUIElement")
    window = _attr(AS, app, "AXFocusedWindow")

    # 1. a native or editable text element with a real selection
    if focused is not None:
        rng = _cfrange(AS, _attr(AS, focused, "AXSelectedTextRange"))
        if rng and rng[1] > 0 and _settable(AS, focused, "AXSelectedTextRange"):
            import Foundation

            value = AS.AXValueCreate(AS.kAXValueTypeCFRange, Foundation.NSRange(rng[0] + rng[1], 0))
            if AS.AXUIElementSetAttributeValue(focused, "AXSelectedTextRange", value) == 0:
                time.sleep(0.3)
                after = _cfrange(AS, _attr(AS, focused, "AXSelectedTextRange"))
                return "collapsed" if not after or after[1] == 0 else "ignored by the app"

    # 2. web content: the selection lives on the web area, addressed by text markers
    web = _web_area(AS, focused, window)
    if web is not None:
        current = _attr(AS, web, "AXSelectedTextMarkerRange")
        length = _param(AS, web, "AXLengthForTextMarkerRange", current) if current is not None else None
        if current is not None and length:
            end = AS.AXTextMarkerRangeCopyEndMarker(current)
            collapsed = AS.AXTextMarkerRangeCreate(None, end, end)
            if AS.AXUIElementSetAttributeValue(web, "AXSelectedTextMarkerRange", collapsed) == 0:
                time.sleep(0.3)
                now = _attr(AS, web, "AXSelectedTextMarkerRange")
                still = _param(AS, web, "AXLengthForTextMarkerRange", now) if now is not None else 0
                return "collapsed" if not still else "ignored by the app"
            return "unsupported"
        return "nothing selected"
    return "unsupported"
