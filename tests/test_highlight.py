import time

from voicechat import highlight as H


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
