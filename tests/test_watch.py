import time

from softvoice import highlight as H
from softvoice import watch as W
from softvoice.watch import Block, ChatWatcher, Detector, View


def view(*blocks, composer="", hooked=False):
    return View(blocks=[Block(role=r, pieces=[t]) for r, t in blocks], composer=composer, hooked=hooked)


def test_reply_after_a_prompt_is_spoken_once_when_it_settles():
    d = Detector(settle_s=2.0)
    assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug")), now=0.0) is None  # first reading: a prompt is out
    assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug"), ("assistant", "Looking at")), now=1.5) is None
    assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug"), ("assistant", "Looking at the login code now.")), now=3.0) is None
    assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug"), ("assistant", "Looking at the login code now.")), now=4.0) is None, "not settled yet"
    assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug"), ("assistant", "Looking at the login code now.")), now=5.1) == "Looking at the login code now."
    for t in (6.0, 10.0, 60.0):  # the same text is never spoken twice
        assert d.feed(view(("assistant", "Earlier reply."), ("user", "Fix the bug"), ("assistant", "Looking at the login code now.")), now=t) is None


def test_an_old_reply_scrolled_into_view_is_not_spoken():
    d = Detector(settle_s=1.0)
    assert d.feed(view(("user", "Second question"), ("assistant", "Second answer.")), now=0.0) is None  # nothing is due
    # the user scrolls up: older messages come in, the newest leave the virtualised list
    for t in (1.0, 2.5, 4.0):
        assert d.feed(view(("user", "First question"), ("assistant", "First answer, long ago.")), now=t) is None
    # and a new reply with no prompt of yours in view stays silent too
    for t in (5.0, 6.5, 8.0):
        assert d.feed(view(("assistant", "Something else entirely.")), now=t) is None


def test_a_reply_arriving_while_you_watch_is_spoken_without_a_prompt_in_view():
    d = Detector(settle_s=1.0)
    assert d.feed(view(("assistant", "The answer is")), now=0.0) is None
    assert d.feed(view(("assistant", "The answer is forty-two, and")), now=1.0) is None  # growing: a live reply
    assert d.feed(view(("assistant", "The answer is forty-two, and here is why.")), now=2.0) is None
    assert d.feed(view(("assistant", "The answer is forty-two, and here is why.")), now=3.5) == "The answer is forty-two, and here is why."


def test_your_own_words_are_never_spoken_when_the_app_does_not_mark_authors():
    d = Detector(settle_s=1.0)
    d.note_user_text("Please summarise this file")  # what the pill pasted
    assert d.feed(view(("", "Old reply."), composer="Please summarise this file"), now=0.0) is None
    # the prompt lands as a message: unknown role, but it is what you wrote
    assert d.feed(view(("", "Old reply."), ("", "Please summarise this file")), now=1.0) is None
    for t in (2.0, 3.0, 5.0):
        assert d.feed(view(("", "Old reply."), ("", "Please summarise this file")), now=t) is None, "the prompt was read back"
    assert d.feed(view(("", "Old reply."), ("", "Please summarise this file"), ("", "It is a config loader.")), now=6.0) is None
    assert d.feed(view(("", "Old reply."), ("", "Please summarise this file"), ("", "It is a config loader.")), now=7.5) == "It is a config loader."


def test_composer_draft_that_becomes_the_prompt_is_recognised():
    d = Detector(settle_s=1.0)
    assert d.feed(view(("", "Hi there."), composer="what time is it"), now=0.0) is None
    assert d.feed(view(("", "Hi there."), ("", "What time is it")), now=1.0) is None  # sent: the draft is now a message
    assert d.prompt == "what time is it"
    assert d.feed(view(("", "Hi there."), ("", "What time is it"), ("", "Noon.")), now=2.0) is None
    assert d.feed(view(("", "Hi there."), ("", "What time is it"), ("", "Noon.")), now=3.5) == "Noon."


def test_window_without_message_markup_is_split_at_your_prompt():
    d = Detector(settle_s=1.0)
    d.note_user_text("Tell me a joke")
    page = "ChatGPT  New chat  Earlier stuff here. Tell me a joke"
    assert d.feed(view(("", page)), now=0.0) is None
    assert d.prompt == "tell me a joke"
    page2 = page + " Why did the chicken cross the road? To get to the other side."
    assert d.feed(view(("", page2)), now=1.0) is None
    assert d.feed(view(("", page2)), now=2.5) == "Why did the chicken cross the road? To get to the other side."
    # nothing of yours in view: nothing can be told apart, so nothing is spoken
    d2 = Detector(settle_s=1.0)
    for t in (0.0, 1.0, 2.5, 4.0):
        assert d2.feed(view(("", "Some page text that keeps growing" + " and more" * int(t))), now=t) is None


def test_hooked_views_and_unreadable_windows_change_nothing():
    d = Detector(settle_s=1.0)
    assert d.feed(view(("user", "Fix it")), now=0.0) is None
    assert d.feed(view(("assistant", "A Code tab reply."), hooked=True), now=1.0) is None
    assert d.feed(View(problem="no window readable"), now=2.0) is None
    assert d.prompt == "fix it" and d.last is not None and d.last[-1].role == "user"
    assert d.feed(view(("user", "Fix it"), ("assistant", "Fixed.")), now=3.0) is None
    assert d.feed(view(("user", "Fix it"), ("assistant", "Fixed.")), now=4.5) == "Fixed."


def test_a_message_that_grows_after_it_was_read_only_adds_the_new_part():
    d = Detector(settle_s=1.0)
    d.feed(view(("user", "Go")), now=0.0)
    d.feed(view(("user", "Go"), ("assistant", "First part.")), now=1.0)
    assert d.feed(view(("user", "Go"), ("assistant", "First part.")), now=2.5) == "First part."
    d.feed(view(("user", "Go"), ("assistant", "First part. Second part.")), now=3.0)
    assert d.feed(view(("user", "Go"), ("assistant", "First part. Second part.")), now=4.5) == "Second part."


def test_hooked_view_detection():
    assert W.is_hooked_view("On-device speech - Claude Code", "https://claude.ai/epitaxy/local_123")
    assert W.is_hooked_view("Anything", "https://claude.ai/code/abc")
    assert not W.is_hooked_view("Claude", "https://claude.ai/chat/abc")
    assert not W.is_hooked_view(None, None)


def test_join_pieces_keeps_sentences_together_and_separates_paragraphs():
    assert W.join_pieces(["Done. Three changes:", "Removed", " the paragraph.", "Rewrote", " the rest."]) == \
        "Done. Three changes:\nRemoved the paragraph.\nRewrote the rest."
    assert W.join_pieces(["The new text is in ", "README", " if you want it."]) == "The new text is in README if you want it."
    assert W.join_pieces(["Summary", "The fix is small."]) == "Summary\nThe fix is small."


# -- reading a window: a fake accessibility tree shaped like the probe showed ------------

def node(role, *children, **attrs):
    d = {"AXRole": role, "AXChildren": list(children)}
    d.update(attrs)
    return d


class FakeAS:
    """Just enough of ApplicationServices for snapshot_window: elements are dicts."""

    def __init__(self, window):
        self.window = window

    def AXUIElementCreateSystemWide(self):
        return {}

    def AXUIElementSetMessagingTimeout(self, el, s):
        return 0

    def AXUIElementCreateApplication(self, pid):
        return {"AXRole": "AXApplication", "AXWindows": [self.window]}

    def AXUIElementSetAttributeValue(self, el, name, value):
        return 0

    def AXUIElementCopyAttributeValue(self, el, name, _):
        if name in el:
            return 0, el[name]
        return -25205, None


def text(value):
    return node("AXStaticText", AXValue=value)


def article(n, heading, *body):
    return node("AXGroup", node("AXHeading", text(heading), AXTitle=heading), *body,
                node("AXToolbar", node("AXGroup", text("8 minutes ago"), AXSubrole="AXTimeGroup")),
                AXSubrole="AXDocumentArticle", AXDescription=f"Message {n}")


def test_read_view_sorts_the_claude_apps_tree_into_messages(monkeypatch):
    feed = node("AXGroup",
                text("Use the up and down arrow keys to move between messages."),
                article(1, "You said: Fix the login bug", node("AXGroup", text("Fix the login bug"))),
                article(2, "Claude responded: Done, uncommitted.",
                        text("Done, uncommitted. Three changes:"),
                        node("AXList", node("AXGroup", node("AXListMarker", AXValue="• "),
                                            node("AXGroup", text("Removed"), AXSubrole="AXStrongStyleGroup"),
                                            text(" the old paragraph.")),
                             AXSubrole="AXContentList"),
                        node("AXGroup", text("x = 1"), AXSubrole="AXCodeStyleGroup")),
                AXSubrole="AXApplicationGroup", AXDescription="Chat messages")
    composer = node("AXTextArea", AXValue="my half-typed next question", AXDescription="Prompt")
    web = node("AXWebArea", node("AXGroup", feed, composer), AXTitle="Some chat", AXURL="https://claude.ai/chat/abc")
    window = node("AXWindow", node("AXGroup", web), AXMain=True, AXTitle="Claude")
    monkeypatch.setattr(H, "_ax", lambda: FakeAS(window))
    monkeypatch.setattr(H, "element_frame", lambda el: None)
    v = W.read_view(4242)
    assert not v.hooked and not v.problem
    assert v.composer == "my half-typed next question"
    assert [(b.role, b.text) for b in v.blocks] == [
        ("user", "Fix the login bug"),
        ("assistant", "Done, uncommitted. Three changes:\nRemoved the old paragraph."),
    ]
    # the underline's own snapshot is untouched by the hook: all text, no contexts asked for
    snap = H.snapshot_window(4242)
    assert "Claude responded: Done, uncommitted." in snap.joined and "x = 1" in snap.joined
    assert snap.contexts == [None] * len(snap.segments)


def test_read_view_flags_the_code_tab_and_falls_back_to_one_block(monkeypatch):
    web = node("AXWebArea", node("AXGroup", text("Hello"), text("world")),
               AXTitle="My session - Claude Code", AXURL="https://claude.ai/epitaxy/local_1")
    window = node("AXWindow", web, AXMain=True)
    monkeypatch.setattr(H, "_ax", lambda: FakeAS(window))
    monkeypatch.setattr(H, "element_frame", lambda el: None)
    v = W.read_view(4242)
    assert v.hooked
    assert [(b.role, b.text) for b in v.blocks] == [("", "Hello world")]  # no markup: one block of everything


def test_author_classes_split_messages_where_articles_are_missing(monkeypatch):
    web = node("AXWebArea",
               node("AXGroup", text("What is 2+2?"), AXDOMClassList=["font-user-message", "x"]),
               node("AXGroup", text("It is 4."), AXDOMClassList=["font-claude-response"]),
               AXTitle="Claude", AXURL="https://claude.ai/chat/x")
    window = node("AXWindow", web, AXMain=True)
    monkeypatch.setattr(H, "_ax", lambda: FakeAS(window))
    monkeypatch.setattr(H, "element_frame", lambda el: None)
    v = W.read_view(1)
    assert [(b.role, b.text) for b in v.blocks] == [("user", "What is 2+2?"), ("assistant", "It is 4.")]


# -- the watcher: polls only a ticked app in front, never while a reply is spoken ----------

def test_watcher_reads_only_ticked_front_apps_and_speaks_once(monkeypatch):
    monkeypatch.setattr(H, "screen_locked", lambda: False)
    reads, spoken, log = [], [], []
    front = {"pid": 10, "bundle": "com.anthropic.claudefordesktop"}
    busy = {"on": False}
    views = iter([
        view(("user", "Fix it")),
        view(("user", "Fix it"), ("assistant", "Fixed the bug.")),
        view(("user", "Fix it"), ("assistant", "Fixed the bug.")),
        view(("user", "Fix it"), ("assistant", "Fixed the bug.")),
    ])

    def read_view(pid):
        reads.append(pid)
        return next(views)

    w = ChatWatcher(speak=lambda text, bundle: spoken.append((text, bundle)), front=lambda: (front["pid"], front["bundle"]),
                    busy=lambda: busy["on"], log=log.append, apps=["com.anthropic.claudefordesktop"], settle_s=1.0,
                    read_view=read_view)
    front["bundle"] = "com.apple.Terminal"
    assert w.tick(now=0.0) is None and reads == []  # not a watched app: the window is not read at all
    front["bundle"] = "com.anthropic.claudefordesktop"
    busy["on"] = True
    assert w.tick(now=0.0) is None and reads == []  # a hooked reply is being spoken: leave the window alone
    busy["on"] = False
    assert w.tick(now=0.0) is None
    assert w.tick(now=1.5) is None
    assert w.tick(now=3.0) == "Fixed the bug."
    assert w.tick(now=4.5) is None
    assert spoken == [("Fixed the bug.", "com.anthropic.claudefordesktop")]
    assert reads == [10, 10, 10, 10]
    assert any("reading a new reply" in line for line in log)


def test_watcher_thread_runs_only_while_enabled(monkeypatch):
    monkeypatch.setattr(H, "screen_locked", lambda: False)
    ticks = []
    w = ChatWatcher(speak=lambda t, b: None, front=lambda: (1, "com.openai.chat"), busy=lambda: False,
                    apps=["com.openai.chat"], poll_s=0.01, read_view=lambda pid: ticks.append(pid) or View())
    assert not w.enabled
    w.set_enabled(True)
    time.sleep(0.1)
    assert w.enabled and ticks
    w.set_enabled(False)
    time.sleep(0.05)
    n = len(ticks)
    time.sleep(0.05)
    assert len(ticks) == n and not w.enabled, "the watcher kept polling after it was switched off"


def test_pasted_text_is_never_read_back(monkeypatch):
    monkeypatch.setattr(H, "screen_locked", lambda: False)
    spoken = []
    page = [view(("", "Welcome."))]
    w = ChatWatcher(speak=lambda t, b: spoken.append(t), front=lambda: (1, "com.openai.chat"), busy=lambda: False,
                    apps=["com.openai.chat"], settle_s=1.0, read_view=lambda pid: page[0])
    w.note_user_text("Write a haiku about rain")
    w.tick(now=0.0)
    page[0] = view(("", "Welcome."), ("", "Write a haiku about rain"))
    for t in (1.0, 2.5, 4.0):
        assert w.tick(now=t) is None
    page[0] = view(("", "Welcome."), ("", "Write a haiku about rain"), ("", "Soft rain on the roof. Sleep comes."))
    w.tick(now=5.0)
    assert w.tick(now=6.5) == "Soft rain on the roof. Sleep comes."
    assert spoken == ["Soft rain on the roof. Sleep comes."]


def test_save_setting_rewrites_only_its_line(tmp_path):
    from softvoice.config import Config, save_setting

    path = tmp_path / "config.toml"
    path.write_text(Config().to_toml())
    save_setting("watch_chats", True, path)
    save_setting("watch_apps", ["com.openai.chat"], path)
    save_setting("watch_chats", False, path)
    cfg = Config.load(path)
    assert (cfg.watch_chats, cfg.watch_apps) == (False, ["com.openai.chat"])
    lines = path.read_text().splitlines()
    assert lines.count("watch_chats = false") == 1 and not any(l.startswith("# watch_chats") for l in lines)
    assert "# voice = \"alba\"" in lines  # the rest of the file is as it was
    path.write_text('voice = "jane"\n')  # a hand-written file without the setting gets it appended
    save_setting("watch_apps", ["com.anthropic.claudefordesktop"], path)
    assert Config.load(path).voice == "jane" and Config.load(path).watch_apps == ["com.anthropic.claudefordesktop"]
