import time

from softvoice import highlight as H


def test_follow_loop_tracks_moving_text_and_stops_on_hide(monkeypatch):
    monkeypatch.setattr(H, "IDLE_POLL_S", 0.01)
    monkeypatch.setattr(H, "SCROLL_GAP_S", 0.0)
    calls = []
    h = H.Highlighter(run_on_main=lambda fn: fn())
    h._show = lambda rects: calls.append(("show", tuple(rects)))
    h._hide = lambda: calls.append(("hide",))
    positions = iter([
        [(0, 100, 50, 18)],  # first reading
        [(0, 100, 50, 18)],  # unchanged: no redraw
        [(0, 80, 50, 18)],  # the page scrolled
        [],  # scrolled out of view
        [(0, 60, 50, 18)],  # back in view
    ])
    h._rects = lambda sentence, snap: next(positions, [(0, 60, 50, 18)])
    h.snap = H.Snapshot()
    h.generation = 1
    h.show_for("hello")
    time.sleep(0.25)
    h.hide()
    time.sleep(0.05)
    settled = list(calls)
    time.sleep(0.05)
    assert calls == settled, "the follow loop kept running after hide()"
    assert settled[:4] == [
        ("show", ((0, 100, 50, 18),)),
        ("show", ((0, 80, 50, 18),)),
        ("hide",),
        ("show", ((0, 60, 50, 18),)),
    ]
    assert settled[-1] == ("hide",)


def test_scroll_nudge_rereads_at_once(monkeypatch):
    monkeypatch.setattr(H, "IDLE_POLL_S", 5.0)  # the safety poll is far away: only a nudge can trigger a read
    monkeypatch.setattr(H, "SCROLL_GAP_S", 0.0)
    calls = []
    h = H.Highlighter(run_on_main=lambda fn: fn())
    h._show = lambda rects: calls.append(tuple(rects))
    h._hide = lambda: calls.append("hide")
    y = [100]
    h._rects = lambda sentence, snap: [(0, y[0], 50, 18)]
    h.snap = H.Snapshot()
    h.generation = 1
    h.show_for("hello")
    time.sleep(0.05)
    assert calls == [((0, 100, 50, 18),)]
    y[0] = 80  # the page scrolled...
    time.sleep(0.05)
    assert calls == [((0, 100, 50, 18),)], "nothing should move before a scroll event or the slow poll"
    h.nudge()  # ...and the event tap says so
    time.sleep(0.05)
    assert calls == [((0, 100, 50, 18),), ((0, 80, 50, 18),)]
    h.hide()


def test_window_is_read_again_while_the_sentence_is_spoken(monkeypatch):
    """A busy app (Electron re-rendering a long reply) answers late: the first reads fail, the
    underline keeps trying in the background and appears once the window can be read."""
    monkeypatch.setattr(H, "screen_locked", lambda: False)  # the test may run on a locked Mac
    monkeypatch.setattr(H, "IDLE_POLL_S", 0.01)
    monkeypatch.setattr(H, "SCROLL_GAP_S", 0.0)
    monkeypatch.setattr(H, "RECOLLECT_EVERY_S", 0.0)
    monkeypatch.setattr(H, "_front_pid", lambda: 4242)
    monkeypatch.setattr(H, "trusted", lambda: True)
    monkeypatch.setattr(H, "_app_name", lambda pid: "Busy")
    reads = [0]

    def snapshot_window(pid):
        reads[0] += 1
        snap = H.Snapshot(taken_at=time.monotonic())
        if reads[0] < 3:
            snap.problem = "no window readable (the app lists no window yet)"
        else:
            snap.joined = "hello there"
        return snap

    monkeypatch.setattr(H, "snapshot_window", snapshot_window)
    log, calls = [], []
    h = H.Highlighter(run_on_main=lambda fn: fn(), log=log.append)
    h._show = lambda rects: calls.append(("show", tuple(rects)))
    h._hide = lambda: calls.append(("hide",))
    h._rects = lambda sentence, snap: [(0, 100, 50, 18)] if snap.joined else []
    h.begin()
    h.show_for("hello")
    time.sleep(0.3)
    h.hide()
    assert reads[0] >= 3, "the window was not read again after the failed reads"
    assert ("show", ((0, 100, 50, 18),)) in calls, "the underline never appeared once the window was readable"
    problems = [line for line in log if "no window readable" in line]
    assert len(problems) == 1 and "retrying" in problems[0], log
    assert any("became readable" in line for line in log), log


def test_locked_screen_is_not_read_until_it_unlocks(monkeypatch):
    monkeypatch.setattr(H, "IDLE_POLL_S", 0.01)
    monkeypatch.setattr(H, "SCROLL_GAP_S", 0.0)
    monkeypatch.setattr(H, "RECOLLECT_EVERY_S", 0.0)
    monkeypatch.setattr(H, "_front_pid", lambda: 4242)
    monkeypatch.setattr(H, "trusted", lambda: True)
    locked = [True]
    monkeypatch.setattr(H, "screen_locked", lambda: locked[0])
    reads = []

    def snapshot_window(pid):
        reads.append(time.monotonic())
        return H.Snapshot(taken_at=time.monotonic(), joined="hello there")

    monkeypatch.setattr(H, "snapshot_window", snapshot_window)
    log, calls = [], []
    h = H.Highlighter(run_on_main=lambda fn: fn(), log=log.append)
    h._show = lambda rects: calls.append(("show", tuple(rects)))
    h._hide = lambda: calls.append(("hide",))
    h._rects = lambda sentence, snap: [(0, 100, 50, 18)] if snap.joined else []
    h.begin()
    h.show_for("hello")
    time.sleep(0.15)
    assert reads == [], "the window was read while the screen was locked"
    assert [line for line in log if "locked" in line] == ["underline: the screen is locked; waiting for it to unlock"]
    locked[0] = False  # the user comes back
    time.sleep(0.15)
    h.hide()
    assert reads, "the window was not read after the screen unlocked"
    assert ("show", ((0, 100, 50, 18),)) in calls
    assert any("became readable" in line for line in log), log
