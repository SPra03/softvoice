"""Best effort: highlight the sentence being read, drawn over the front window's own text.

macOS accessibility lets us read the text of the front app's window and ask for the screen
rectangle of a character range. We join the window's text in reading order, find the sentence
the speaker is on, measure it line by line, and float soft translucent bars over those lines.
Works where the app exposes its text (web views such as the Claude desktop app, Terminal, VS
Code, most native apps); silently does nothing elsewhere.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field

TEXT_ROLES = {"AXStaticText", "AXTextArea", "AXTextField"}
SKIP_ROLES = {"AXApplication", "AXMenuBar", "AXMenuBarItem", "AXMenu", "AXMenuItem", "AXToolbar",
              "AXScrollBar", "AXPopUpButton", "AXImage"}
MAX_NODES = 8000
WALK_BUDGET_S = 3.0
WINDOW_WAIT_S = 4.0
AX_TIMEOUT_S = 1.5  # a busy app (Electron re-rendering a long reply) answers late; give up on a call this soon and retry
RECOLLECT_EVERY_S = 1.5
IDLE_POLL_S = 0.5  # safety re-read of the underline's position when no scroll event arrives
SCROLL_GAP_S = 1 / 60  # while scrolling, re-read at most this often
MAX_BARS = 6
UNDERLINE_H = 2.0  # the underline's thickness, in points
UNDERLINE_GAP = 1.0  # how far below the line box it sits


def _ax():
    import ApplicationServices as AS

    return AS


def _attr(AS, element, name):
    err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None


AX_ERRORS = {-25211: "accessibility API disabled: this process is not trusted under Privacy & Security > Accessibility",
             -25204: "the app does not answer accessibility requests", -25205: "attribute unsupported",
             -25202: "invalid element", -25212: "no value", -25200: "accessibility failure"}


def trusted() -> bool | None:
    try:
        return bool(_ax().AXIsProcessTrusted())
    except Exception:
        return None


def screen_locked() -> bool:
    """While the screen is locked every app answers accessibility with an empty shell, so reading is pointless."""
    try:
        import Quartz

        return bool((Quartz.CGSessionCopyCurrentDictionary() or {}).get("CGSSessionScreenIsLocked", 0))
    except Exception:
        return False


def _front_pid() -> int | None:
    from softvoice.front import front_pid

    return front_pid()


def _app_name(pid: int) -> str:
    try:
        from AppKit import NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        return str(app.localizedName()) if app else "?"
    except Exception:
        return "?"


def _to_appkit(x, y, w, h):
    from AppKit import NSScreen

    primary = NSScreen.screens()[0].frame()  # AX uses a top-left origin; AppKit a bottom-left one
    return (x, primary.size.height - (y + h), w, h)


@dataclass
class Snapshot:
    """The window's text in reading order, with each piece's node and offset in the joined string."""

    window: object = None
    frame: tuple | None = None
    segments: list[tuple[object, str, int]] = field(default_factory=list)  # (node, text, offset)
    joined: str = ""
    taken_at: float = 0.0
    problem: str = ""  # why there is nothing to underline, for the log
    nodes: int = 0

    @property
    def joined_lower(self) -> str:
        return self.joined.lower()


def _pick_window(AS, app):
    """The app's main window: role AXWindow, main if possible, else the first. A busy app may list its
    windows but not answer for them yet; then the first listed window is taken as it is."""
    listed = list(_attr(AS, app, "AXWindows") or [])
    windows = [w for w in listed if _attr(AS, w, "AXRole") == "AXWindow"] or listed
    for w in windows:
        if _attr(AS, w, "AXMain"):
            return w
    return windows[0] if windows else None


def snapshot_window(pid: int) -> Snapshot:
    if pid == os.getpid():
        return Snapshot()
    AS = _ax()
    try:  # calls into a busy app would otherwise hang for the 6 s system default, each
        AS.AXUIElementSetMessagingTimeout(AS.AXUIElementCreateSystemWide(), AX_TIMEOUT_S)
    except Exception:
        pass
    app = AS.AXUIElementCreateApplication(pid)
    # Electron apps keep their accessibility tree off until a client asks for it, and need a moment.
    AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    deadline = time.monotonic() + WINDOW_WAIT_S
    window = _pick_window(AS, app)
    while window is None and time.monotonic() < deadline:
        time.sleep(0.25)
        window = _pick_window(AS, app)
    snap = Snapshot(window=window, taken_at=time.monotonic())
    if window is None:
        err, _ = AS.AXUIElementCopyAttributeValue(app, "AXWindows", None)
        why = "the app lists no window yet" if err == 0 else AX_ERRORS.get(err, f"accessibility error {err}")
        snap.problem = f"no window readable ({why})"
        return snap
    snap.frame = element_frame(window)
    stack = [(window, 0)]  # depth-first, children in order: reading order
    seen = 0
    pieces: list[tuple[object, str]] = []
    deadline = time.monotonic() + WALK_BUDGET_S
    while stack and seen < MAX_NODES and time.monotonic() < deadline:
        node, depth = stack.pop()
        seen += 1
        role = _attr(AS, node, "AXRole")
        if role in SKIP_ROLES or depth > 60:
            continue
        if role in TEXT_ROLES:
            value = _attr(AS, node, "AXValue")
            if isinstance(value, str) and value.strip():
                pieces.append((node, value))
        children = _attr(AS, node, "AXChildren")
        if children:
            stack.extend((c, depth + 1) for c in reversed(children))
    offset = 0
    parts = []
    for node, text in pieces:
        snap.segments.append((node, text, offset))
        parts.append(text)
        offset += len(text) + 1  # one space between pieces
    snap.joined = " ".join(parts)
    snap.nodes = seen
    if not snap.joined:
        snap.problem = f"the window exposes no text through accessibility ({seen} elements seen)"
    return snap


def element_frame(element):
    """(x, y, w, h) of an element in AppKit coordinates, or None."""
    AS = _ax()
    rect_type = getattr(AS, "kAXValueTypeCGRect", None) or getattr(AS, "kAXValueCGRectType")
    value = _attr(AS, element, "AXFrame")
    if value is None:
        return None
    ok, rect = AS.AXValueGetValue(value, rect_type, None)
    if not ok:
        return None
    return _to_appkit(rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)


_WORD = re.compile(r"[a-z0-9']+")


def locate(sentence: str, snap: Snapshot) -> tuple[int, int] | None:
    """(start, end) of the sentence in the snapshot's joined text; the last occurrence wins,
    since the newest reply sits lowest on the page."""
    words = _WORD.findall(sentence.lower())
    if len(words) < 2:
        return None
    head = words[:6]
    tail = words[-3:] if len(words) >= 6 else []
    head_re = re.compile(r"[^a-z0-9]+".join(map(re.escape, head)))
    low = snap.joined_lower
    matches = list(head_re.finditer(low))
    if not matches:
        return None
    m = matches[-1]
    start = m.start()
    end = min(len(low), start + len(sentence))
    if tail:
        tail_re = re.compile(r"[^a-z0-9]+".join(map(re.escape, tail)))
        m2 = tail_re.search(low, m.end(), min(len(low), start + int(len(sentence) * 1.8) + 20))
        if m2:
            end = m2.end()
    return start, max(start + 1, end)


def pieces_for(snap: Snapshot, start: int, end: int) -> list[tuple[object, str, int, int]]:
    """Which nodes a joined-text range touches: (node, node text, local start, local length)."""
    out = []
    for node, text, offset in snap.segments:
        seg_end = offset + len(text)
        lo, hi = max(start, offset), min(end, seg_end)
        if hi > lo:
            out.append((node, text, lo - offset, hi - lo))
    return out


def _u16(text: str, index: int) -> int:
    """Accessibility counts UTF-16 code units; Python counts code points. Emoji differ."""
    return len(text[:index].encode("utf-16-le")) // 2


def bounds_for_range(element, start: int, length: int, text: str | None = None):
    """Screen rectangle (x, y, w, h) in AppKit coordinates for a text range, or None.
    With `text`, start and length are Python indices into it and are converted for AX."""
    AS = _ax()
    from Foundation import NSRange

    if text is not None:
        u_start = _u16(text, start)
        length = _u16(text, start + length) - u_start
        start = u_start
    range_type = getattr(AS, "kAXValueTypeCFRange", None) or getattr(AS, "kAXValueCFRangeType")
    rect_type = getattr(AS, "kAXValueTypeCGRect", None) or getattr(AS, "kAXValueCGRectType")
    try:
        param = AS.AXValueCreate(range_type, NSRange(start, length))
    except Exception:
        param = AS.AXValueCreate(range_type, (start, length))
    err, value = AS.AXUIElementCopyParameterizedAttributeValue(element, "AXBoundsForRange", param, None)
    if err != 0 or value is None:
        return None
    ok, rect = AS.AXValueGetValue(value, rect_type, None)
    if not ok:
        return None
    x, y, w, h = rect.origin.x, rect.origin.y, rect.size.width, rect.size.height
    if w <= 0 or h <= 0:
        return None
    return _to_appkit(x, y, w, h)


def line_rects(node, text: str, start: int, length: int) -> list[tuple]:
    """One rectangle per rendered line of the range. The bounding box of a range grows a whole
    line taller once it reaches the next line, so a binary search over the end offset finds each
    line break exactly, even inside a hyphenated or dashed word."""
    end = start + length
    rects: list[tuple] = []
    line_start = start

    def h(a: int, b: int):
        r = bounds_for_range(node, a, b - a, text)
        return (r[3] if r else None), r

    while line_start < end and len(rects) < MAX_BARS:
        probe_h, _ = h(line_start, min(end, line_start + 2))
        full_h, full = h(line_start, end)
        if probe_h is None or full is None:
            break
        if full_h <= probe_h * 1.6:
            rects.append(full)
            break
        lo, hi = line_start + 1, end  # h(lo) fits on this line, h(hi) does not
        while hi - lo > 1:
            mid = (lo + hi) // 2
            mid_h, _ = h(line_start, mid)
            if mid_h is not None and mid_h <= probe_h * 1.6:
                lo = mid
            else:
                hi = mid
        _, line = h(line_start, lo)
        if line:
            rects.append(line)
        if lo <= line_start:
            break
        line_start = lo
    return rects


def clip(rect, frame):
    """The part of rect inside frame, or None when they don't overlap enough to be worth showing."""
    if rect is None:
        return None
    if frame is None:
        return rect
    x0, y0 = max(rect[0], frame[0]), max(rect[1], frame[1])
    x1, y1 = min(rect[0] + rect[2], frame[0] + frame[2]), min(rect[1] + rect[3], frame[1] + frame[3])
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def rects_for_sentence(sentence: str, snap: Snapshot) -> list[tuple]:
    hit = locate(sentence, snap)
    if not hit:
        return []
    rects: list[tuple] = []
    for node, text, local_start, local_len in pieces_for(snap, *hit):
        for r in line_rects(node, text, local_start, local_len):
            c = clip(r, snap.frame)  # scrolled-away text gets no bar
            if c:
                rects.append(c)
        if len(rects) >= MAX_BARS:
            break
    return rects[:MAX_BARS]


class Highlighter:
    def __init__(self, run_on_main, color: tuple[float, float, float] = (0.67, 0.67, 0.67), other_pid=None, log=None):
        self.color = color  # the underline's colour, (r, g, b) in 0..1
        self.other_pid = other_pid  # callable -> pid of the last front app that is not us (the session tracks it)
        self.run_on_main = run_on_main
        self.log = log or (lambda msg: None)  # one line per reply when there is nothing to underline, and why
        self.overlays: list = []
        self.lock = threading.Lock()
        self.pid: int | None = None
        self.last_other_pid: int | None = None  # the last front app that wasn't us
        self.snap: Snapshot | None = None
        self.generation = 0  # bumped per reply
        self.began_at = 0.0
        self.collecting = False  # a background read of the window is in flight
        self.problem_gen = 0  # the reply whose first unreadable window was logged, so retries stay quiet
        self.show_seq = 0  # bumped per sentence shown, and on hide: stops the older follow loops
        self.moved = threading.Event()  # set by nudge(): the page scrolled, re-read now

    # -- background --

    def begin(self) -> None:
        """A reply starts: remember the front app and read its text, in the background."""
        self.generation += 1
        pid = _front_pid()
        if pid and pid != os.getpid():
            self.last_other_pid = pid
        elif self.other_pid is not None:  # we are in front: the session knows who was before us
            self.last_other_pid = self.other_pid() or self.last_other_pid
        self.pid = self.last_other_pid  # never read our own pill; it carries the same sentence
        self.began_at = time.monotonic()
        with self.lock:
            self.snap = None
        if not self.pid:
            self.log("underline: no front app to read")
        elif trusted() is False:
            self.log("underline: Accessibility is not granted to this process (Privacy & Security > Accessibility)")
        threading.Thread(target=self._collect, args=(self.generation,), daemon=True).start()

    def _collect(self, gen: int) -> Snapshot | None:
        with self.lock:
            self.collecting = True
        snap = None
        try:
            if self.pid and screen_locked():
                snap = Snapshot(taken_at=time.monotonic(), problem="the screen is locked")
                if gen == self.generation and self.problem_gen != gen:
                    self.problem_gen = gen
                    self.log("underline: the screen is locked; waiting for it to unlock")
            elif self.pid:
                snap = snapshot_window(self.pid)
                if gen == self.generation:
                    if snap.problem and self.problem_gen != gen:  # the first failure of this reply; retries stay quiet
                        self.problem_gen = gen
                        self.log(f"underline: {snap.problem} ({_app_name(self.pid)}, pid {self.pid}); retrying while it speaks")
                    elif not snap.problem and self.problem_gen == gen:
                        self.problem_gen = 0
                        self.log(f"underline: the window became readable after {time.monotonic() - self.began_at:.0f} s")
        except Exception as exc:
            snap = Snapshot()
            self.log(f"underline: could not read the front window: {type(exc).__name__}: {exc}")
        with self.lock:
            self.collecting = False
            if gen == self.generation:
                self.snap = snap
        return snap

    def _recollect(self, gen: int) -> None:
        """Read the window again in the background, unless a read is already running."""
        with self.lock:
            if self.collecting or gen != self.generation:
                return
            self.collecting = True
        threading.Thread(target=self._collect, args=(gen,), daemon=True).start()

    def show_for(self, sentence: str) -> None:
        self.show_seq += 1
        threading.Thread(target=self._show_for, args=(sentence, self.generation, self.show_seq), daemon=True).start()

    def nudge(self) -> None:
        """The page may have moved (a scroll event): re-read the underline's position at once."""
        self.moved.set()

    def _current(self, gen: int, seq: int) -> bool:
        return gen == self.generation and seq == self.show_seq

    def _show_for(self, sentence: str, gen: int, seq: int) -> None:
        deadline = time.monotonic() + WINDOW_WAIT_S + WALK_BUDGET_S
        while time.monotonic() < deadline:  # wait for the first read of the window
            with self.lock:
                snap = self.snap if self._current(gen, seq) else None
            if snap is not None or not self._current(gen, seq):
                break
            time.sleep(0.05)
        if not self._current(gen, seq) or snap is None:
            return
        rects = self._rects(sentence, snap)
        shown = None
        last_read = time.monotonic()
        while self._current(gen, seq):  # follow the text while this sentence is being spoken
            if not rects and time.monotonic() - snap.taken_at > RECOLLECT_EVERY_S:
                self._recollect(gen)  # a busy app, a re-rendered page or text scrolled away: read it again
            if rects != shown:
                shown = rects
                if rects:
                    self.run_on_main(lambda r=rects: self._show(r))
                else:
                    self.run_on_main(self._hide)  # scrolled out of view: back when it scrolls in
            self.moved.wait(IDLE_POLL_S)  # a scroll wakes us at once; otherwise a slow safety read
            self.moved.clear()
            gap = SCROLL_GAP_S - (time.monotonic() - last_read)
            if gap > 0:
                time.sleep(gap)
            if not self._current(gen, seq):
                return
            with self.lock:
                latest = self.snap if gen == self.generation else None
            if latest is not None and latest is not snap:
                snap = latest  # a fresh read landed
            rects = self._rects(sentence, snap)  # same nodes, fresh positions
            last_read = time.monotonic()

    @staticmethod
    def _rects(sentence: str, snap: Snapshot) -> list[tuple]:
        try:
            return rects_for_sentence(sentence, snap)
        except Exception:
            return []

    def hide(self) -> None:
        self.show_seq += 1  # ends the follow loop of the sentence on screen
        self.run_on_main(self._hide)

    # -- main thread --

    def _make_overlay(self):
        from AppKit import (
            NSBackingStoreBuffered,
            NSColor,
            NSPanel,
            NSStatusWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
            NSWindowStyleMaskNonactivatingPanel,
        )
        from Foundation import NSMakeRect

        w = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 10, 10), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        w.setLevel_(NSStatusWindowLevel)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setIgnoresMouseEvents_(True)
        w.setHidesOnDeactivate_(False)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | NSWindowCollectionBehaviorStationary)
        content = w.contentView()
        content.setWantsLayer_(True)
        r, g, b = self.color
        content.layer().setBackgroundColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 0.9).CGColor())
        content.layer().setCornerRadius_(UNDERLINE_H / 2)
        return w

    def _show(self, rects: list[tuple]) -> None:
        from Foundation import NSMakeRect

        while len(self.overlays) < len(rects):
            self.overlays.append(self._make_overlay())
        for i, panel in enumerate(self.overlays):
            if i < len(rects):
                x, y, w, h = rects[i]  # a thin line along the bottom edge of each line box
                panel.setFrame_display_(NSMakeRect(x, y - UNDERLINE_GAP, w, UNDERLINE_H), True)
                panel.orderFrontRegardless()
            else:
                panel.orderOut_(None)

    def _hide(self) -> None:
        for panel in self.overlays:
            panel.orderOut_(None)
