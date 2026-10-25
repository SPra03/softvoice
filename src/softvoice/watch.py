"""Read aloud new replies in chat apps that have no hooks: the Claude app's own chat, ChatGPT.

Claude Code and Codex say when a turn ends (their Stop hook). A chat window does not, so while a
ticked app is in front we read its window through accessibility every second or two, the way the
underline does, and look for a reply: the newest message, written by the assistant, that follows
the prompt you sent and has stopped changing for a couple of seconds. It then goes to the speaker
daemon like a hooked reply, so the pill and the underline follow along.

Never spoken: your own prompt (a message marked as yours, what the pill pasted, what sat in the
composer), anything spoken before, an older message that scrolled into view, and the Claude
app's Code tab, whose replies arrive through the hook. With the switch off nothing is read at all.
"""

from __future__ import annotations

import collections
import re
import threading
import time
from dataclasses import dataclass, field

from softvoice.config import CHAT_APPS

POLL_S = 1.5  # how often a watched window is read while it is in front
SETTLE_S = 2.0  # a reply is spoken once its text has stayed the same this long
# How the apps mark things up. One message per element with one of these subroles (the Claude app
# wraps each message in an <article>).
MESSAGE_SUBROLES = {"AXDocumentArticle"}
# A message's hidden heading names its author ("Claude responded: …", screen-reader text): prefix -> who
AUTHOR_PREFIXES = (("Claude responded:", "assistant"), ("Claude said:", "assistant"), ("ChatGPT said:", "assistant"),
                   ("You said:", "user"))
# Chromium hands us an element's DOM classes; where an app marks the author that way: class -> who
AUTHOR_CLASSES = {"font-claude-response": "assistant", "font-claude-message": "assistant", "font-user-message": "user"}
SKIP_SUBROLES = {"AXTimeGroup", "AXCodeStyleGroup"}  # "8 minutes ago", code: not part of what is read
SKIP_ROLES = {"AXTable", "AXToolbar", "AXTabGroup"}
HOOKED_TITLE_SUFFIX = " - Claude Code"  # the Claude app's Code tab is a web view with this title
HOOKED_URL_PARTS = ("claude.ai/epitaxy/", "claude.ai/code/")
PROMPT_WINDOW = 50  # how many recent prompts and composer drafts are remembered as yours


def app_name(bundle: str) -> str:
    return next((name for name, b in CHAT_APPS if b == bundle), bundle)


def is_hooked_view(title: str | None, url: str | None) -> bool:
    """The Claude app's Code tab: its replies come through the Stop hook, so the watcher leaves it alone."""
    if title and str(title).endswith(HOOKED_TITLE_SUFFIX):
        return True
    return bool(url) and any(part in str(url) for part in HOOKED_URL_PARTS)


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


CLOSING = ",.;:!?)]}\u2019\u201d\"'"  # a run starting with one of these continues the sentence before it
OPENING = "([{\u201c\u2018\"'"  # a run after one of these continues it too


def join_pieces(pieces: list[str]) -> str:
    """Accessibility hands a message over as runs of text: a paragraph, a bold word, the rest of its
    line. A run that continues the sentence (a space on either side of the seam, a lowercase start,
    closing punctuation, or an open quote or bracket before it) is glued on; any other run starts a
    new line, so the voice pauses between paragraphs and list items."""
    lines: list[list[str]] = []
    for piece in pieces:
        if not piece.strip():
            continue
        if not lines:
            lines.append([piece])
            continue
        prev = lines[-1][-1]
        head, tail = piece[0], prev[-1]
        seam_space = head.isspace() or tail.isspace()
        if seam_space or head.islower() or head in CLOSING or tail in OPENING:
            lines[-1].append(piece if seam_space or head in CLOSING or tail in OPENING else " " + piece)
        else:
            lines.append([piece])
    return "\n".join(" ".join("".join(line).split()) for line in lines)


@dataclass
class Block:
    """One message of the conversation, as far as the window tells them apart."""

    role: str = ""  # "assistant", "user", or "" when the app does not say
    pieces: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return join_pieces(self.pieces)


@dataclass
class View:
    """One reading of a watched window."""

    blocks: list[Block] = field(default_factory=list)
    composer: str = ""  # what sits in the window's text fields: the prompt being typed
    hooked: bool = False  # the window shows a hooked agent (the Claude app's Code tab)
    problem: str = ""  # why the window could not be read


class _TreeReader:
    """The `on_node` callback for `highlight.snapshot_window`: sorts the window's text into messages."""

    def __init__(self):
        self.blocks: list[Block] = []
        self.composer: list[str] = []
        self.hooked = False

    def on_node(self, AS, node, role, ctx):
        from softvoice.highlight import SKIP, _attr

        if role in SKIP_ROLES:
            return SKIP
        if role == "AXWebArea":
            if is_hooked_view(_attr(AS, node, "AXTitle"), _attr(AS, node, "AXURL")):
                self.hooked = True
            return ctx
        if role in ("AXTextArea", "AXTextField", "AXComboBox", "AXSearchField"):
            value = _attr(AS, node, "AXValue")
            if isinstance(value, str) and value.strip():
                self.composer.append(value)
            return SKIP  # the prompt being typed is not a message
        if role == "AXGroup":
            subrole = _attr(AS, node, "AXSubrole")
            if subrole in SKIP_SUBROLES:
                return SKIP
            if subrole in MESSAGE_SUBROLES:
                block = Block()
                self.blocks.append(block)
                return block
            classes = _attr(AS, node, "AXDOMClassList")
            if classes:
                for cls in classes:
                    who = AUTHOR_CLASSES.get(str(cls))
                    if who:
                        if isinstance(ctx, Block) and not ctx.pieces:
                            ctx.role = ctx.role or who  # the article's own body names the author
                            return ctx
                        block = Block(role=who)
                        self.blocks.append(block)
                        return block
            return ctx
        if role == "AXHeading" and isinstance(ctx, Block):
            title = str(_attr(AS, node, "AXTitle") or _attr(AS, node, "AXDescription") or "")
            for prefix, who in AUTHOR_PREFIXES:
                if title.startswith(prefix):
                    ctx.role = who
                    return SKIP  # a screen-reader label repeating the first sentence
        return ctx


def read_view(pid: int) -> View:
    """Read the window of `pid` and sort its text into messages."""
    from softvoice.highlight import snapshot_window

    reader = _TreeReader()
    snap = snapshot_window(pid, on_node=reader.on_node)
    view = View(hooked=reader.hooked, composer="\n".join(reader.composer), problem=snap.problem)
    if snap.problem and not snap.joined:
        return view
    loose: list[str] = []
    for (_node, text, _offset), ctx in zip(snap.segments, snap.contexts):
        if isinstance(ctx, Block):
            ctx.pieces.append(text)
        else:
            loose.append(text)
    view.blocks = [b for b in reader.blocks if b.text.strip()]
    if not view.blocks and loose:  # an app without message markup: the window's text is one block
        view.blocks = [Block(pieces=loose)]
    view.problem = ""
    return view


class Detector:
    """Pure: feed it one `View` after another and it says what to speak, once.

    A reply is the newest message when it is the assistant's, it follows a prompt of yours seen
    in the window (or it is visibly growing: a reply arriving while you watch), and it has read
    the same for `settle_s`. Nothing is spoken twice, and nothing that is yours."""

    def __init__(self, settle_s: float = SETTLE_S):
        self.settle_s = settle_s
        self.last: list[Block] | None = None  # the previous reading; None before the first
        self.prompt: str | None = None  # the prompt whose reply is due (normalised), or None
        self.live: str | None = None  # the start of a reply seen growing while you watch, or None
        self.pending: tuple[str, float, str] | None = None  # (normalised candidate, since, text)
        self.spoken: collections.deque[tuple[str, str]] = collections.deque(maxlen=PROMPT_WINDOW)  # (normalised, text)
        self.user_texts: collections.deque[str] = collections.deque(maxlen=PROMPT_WINDOW)

    def note_user_text(self, text: str) -> None:
        """Something you wrote: a pasted dictation, a composer draft, a message marked as yours."""
        key = normalise(text)
        if key and key not in self.user_texts:
            self.user_texts.append(key)

    def reset(self) -> None:
        self.last = None
        self.prompt = None
        self.live = None
        self.pending = None

    def is_users(self, block: Block) -> bool:
        return block.role == "user" or (block.role == "" and normalise(block.text) in self.user_texts)

    def feed(self, view: View, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        if view.hooked or view.problem:
            return None
        if view.composer.strip():
            self.note_user_text(view.composer)
        blocks = self._blocks(view)
        for block in blocks:
            if block.role == "user":
                self.note_user_text(block.text)
        prev, self.last = self.last, blocks
        if not blocks:
            self.pending = None
            return None
        last = blocks[-1]
        key = normalise(last.text)
        prev_last = prev[-1] if prev else None
        if self.is_users(last):
            if prev_last is None or normalise(prev_last.text) != key or not self.is_users(prev_last):
                self.prompt = key  # your prompt went out: a reply is due
            self.live = None
            self.pending = None
            return None
        prev_key = normalise(prev_last.text) if prev_last is not None else ""
        growing = (prev_last is not None and not self.is_users(prev_last) and prev_key != key
                   and (key.startswith(prev_key) or (len(prev_key) >= 40 and key[:40] == prev_key[:40])))
        if growing:
            self.live = key[:40]  # a reply arriving while you watch: no prompt needed
        due = ((self.prompt is not None and any(normalise(b.text) == self.prompt for b in blocks[:-1]))
               or (self.live is not None and key.startswith(self.live)))
        if not key or key in self.user_texts or not due:
            self.pending = None
            return None
        if self.pending is None or self.pending[0] != key:
            self.pending = (key, now, last.text)
            return None
        if now - self.pending[1] < self.settle_s:
            return None
        self.pending = None
        self.prompt = None
        self.live = None
        text = last.text
        for spoken_key, spoken_text in reversed(self.spoken):
            if key == spoken_key:
                return None
            if key.startswith(spoken_key) and text.startswith(spoken_text):
                text = text[len(spoken_text):].strip()  # the message grew after it was read: only the new part
                break
        self.spoken.append((key, last.text))
        return text or None

    def _blocks(self, view: View) -> list[Block]:
        blocks = [b for b in view.blocks if b.text.strip()]
        if len(blocks) == 1 and blocks[0].role == "":
            return self._split_unknown(blocks[0])
        return blocks

    def _split_unknown(self, block: Block) -> list[Block]:
        """An app that does not tell messages apart: the text after the last prompt of yours is the reply."""
        text = block.text
        best = None
        for key in self.user_texts:
            pattern = re.compile(r"\s+".join(re.escape(w) for w in key.split()), re.IGNORECASE)
            for m in pattern.finditer(text):
                if best is None or m.end() > best.end():
                    best = m
        if best is None:
            return []  # nothing of yours in view: nothing can be told apart
        tail = text[best.end():].strip()
        out = [Block(role="user", pieces=[best.group(0)])]
        if tail:
            out.append(Block(pieces=[tail]))
        return out


class ChatWatcher:
    """Polls the front window while it belongs to a ticked app; nothing runs while it is off."""

    def __init__(self, speak, front, busy, log=None, apps=(), settle_s: float = SETTLE_S, poll_s: float = POLL_S,
                 read_view=None):
        self.speak = speak  # callable(text, bundle): send a reply to the speaker
        self.front = front  # callable -> (pid, bundle) of the app you are looking at (never us)
        self.busy = busy  # callable -> True while a reply is being spoken: leave the window alone
        self.log = log or (lambda msg: None)
        self.apps = set(apps)
        self.settle_s = settle_s
        self.poll_s = poll_s
        self.read_view = read_view or globals()["read_view"]
        self.detectors: dict[str, Detector] = {}
        self.pasted: collections.deque[str] = collections.deque(maxlen=20)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._unreadable: str | None = None  # the app whose window was last reported unreadable, logged once

    @property
    def enabled(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_enabled(self, on: bool) -> None:
        with self._lock:
            if on and not self.enabled:
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, name="chat-watch", daemon=True)
                self._thread.start()
                self.log("reading replies from " + ", ".join(app_name(b) for _, b in CHAT_APPS if b in self.apps)
                         + " while in front")
            elif not on and self.enabled:
                self._stop.set()
                self._thread = None
                self.log("reading replies from chat apps: off")

    def set_apps(self, apps) -> None:
        self.apps = set(apps)
        for bundle in [b for b in self.detectors if b not in self.apps]:
            del self.detectors[bundle]

    def note_user_text(self, text: str) -> None:
        """The pill pasted this: never read it back as a reply."""
        if text.strip():
            self.pasted.append(text)
            for det in self.detectors.values():
                det.note_user_text(text)

    def _run(self) -> None:
        failures = 0
        while not self._stop.wait(self.poll_s):
            try:
                self.tick()
                failures = 0
            except Exception as exc:
                failures += 1
                if failures in (1, 10, 100):
                    self.log(f"chat watcher: {type(exc).__name__}: {exc}")

    def tick(self, now: float | None = None) -> str | None:
        from softvoice.highlight import screen_locked

        pid, bundle = self.front()
        if not pid or bundle not in self.apps:
            return None
        if self.busy() or screen_locked():
            return None
        det = self.detectors.get(bundle)
        if det is None:
            det = self.detectors[bundle] = Detector(self.settle_s)
            for text in self.pasted:
                det.note_user_text(text)
        view = self.read_view(pid)
        if view.problem:
            if self._unreadable != bundle:
                self._unreadable = bundle
                self.log(f"chat watcher: cannot read {app_name(bundle)}'s window ({view.problem})")
            return None
        if self._unreadable == bundle:
            self._unreadable = None
        text = det.feed(view, now)
        if text:
            self.log(f"{app_name(bundle)}: reading a new reply ({len(text)} chars)")
            self.speak(text, bundle)
        return text
