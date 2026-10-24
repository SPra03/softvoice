"""A small floating control: a mic and a speaker button, always on top, never steals focus.

Click the mic to start a dictation session: the pill widens into ✕ · live preview · ✓.
Click the speaker to stop the voice, or to replay the last reply when it is quiet.
Right-click, or press and hold, for the options menu. Drag it anywhere; the spot is remembered.
"""

from __future__ import annotations

import json

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSFont,
    NSImage,
    NSLineBreakByWordWrapping,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSRectFillUsingOperation,
    NSScreen,
    NSStatusWindowLevel,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakePoint, NSMakeRect, NSObject, NSTimer, NSZeroRect

from voicechat.config import HOME_DIR, write_default_config

POS_PATH = HOME_DIR / "panel.json"
BTN = 48
PAD = 6
PREVIEW_W = 300
W, H = BTN * 2 + PAD * 3, BTN + PAD * 2
W_EXPANDED = BTN * 2 + PREVIEW_W + PAD * 4
LONG_PRESS_S = 0.45
PREVIEW_CHARS = 220

GREY = NSColor.colorWithWhite_alpha_(0.72, 1.0)
WHITE = NSColor.whiteColor()
RED = NSColor.systemRedColor()
ORANGE = NSColor.systemOrangeColor()
YELLOW = NSColor.systemYellowColor()
GREEN = NSColor.systemGreenColor()

# state -> (mic symbol, mic tint, speaker symbol, speaker tint)
LOOKS = {
    "loading": ("hourglass", GREY, "speaker.wave.2.fill", GREY),
    "idle": ("mic.fill", GREY, "play.fill", GREY),
    "your_turn": ("mic.fill", GREEN, "play.fill", GREY),
    "speaking": ("mic.fill", GREY, "stop.fill", WHITE),
    "open": ("mic.fill", RED, "play.fill", GREY),
    "hearing": ("waveform", RED, "play.fill", GREY),
    "ptt": ("mic.fill", RED, "play.fill", GREY),
    "dictating": ("mic.fill", RED, "play.fill", GREY),
    "dict_hearing": ("waveform", RED, "play.fill", GREY),
    "transcribing": ("hourglass", ORANGE, "play.fill", GREY),
    "review": ("pencil", YELLOW, "play.fill", GREY),
    "muted": ("mic.fill", GREY, "speaker.slash.fill", GREY),
}


class PillButton(NSView):
    """An SF Symbol that acts as a button, with long-press and right-click for a menu and drag-to-move."""

    def initWithFrame_(self, frame):
        self = objc.super(PillButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.image = None
        self.tint = GREY
        self.on_click = None
        self.on_menu = None
        self._timer = None
        self._long_fired = False
        self._down_at = None
        self._dragging = False
        return self

    def acceptsFirstMouse_(self, event):
        return True  # clicks work even though our app is never the active one

    def set_look(self, symbol: str, tint) -> None:
        self.image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, symbol)
        self.tint = tint
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        if self.image is None:
            return
        size = 22.0
        b = self.bounds()
        r = NSMakeRect((b.size.width - size) / 2, (b.size.height - size) / 2, size, size)
        self.image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
            r, NSZeroRect, NSCompositingOperationSourceOver, 1.0, True, None)
        self.tint.set()
        NSRectFillUsingOperation(r, NSCompositingOperationSourceAtop)

    def mouseDown_(self, event):
        self._long_fired = False
        self._dragging = False
        self._down_at = event.locationInWindow()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            LONG_PRESS_S, self, b"longPress:", None, False)

    def mouseDragged_(self, event):
        if self._dragging or self._down_at is None:
            return
        p = event.locationInWindow()
        if abs(p.x - self._down_at.x) > 4 or abs(p.y - self._down_at.y) > 4:
            self._dragging = True
            self._cancel_timer()
            self.window().performWindowDragWithEvent_(event)

    def mouseUp_(self, event):
        self._cancel_timer()
        if not self._long_fired and not self._dragging and self.on_click:
            self.on_click()
        self._down_at = None

    def rightMouseDown_(self, event):
        self._cancel_timer()
        self._show_menu()

    def longPress_(self, timer):
        self._long_fired = True
        self._timer = None
        self._show_menu()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def _show_menu(self):
        if self.on_menu:
            self.on_menu(self)


class MenuActions(NSObject):
    """Target for the options menu; forwards to the session."""

    def initWithPanel_(self, panel):
        self = objc.super(MenuActions, self).init()
        self.panel = panel
        return self

    def toggleHandsFree_(self, sender):
        self.panel.session.set_hands_free(not self.panel.session.hands_free)

    def toggleAutoSend_(self, sender):
        self.panel.session.set_auto_submit(not self.panel.session.auto_submit)

    def toggleMute_(self, sender):
        self.panel.session.set_muted(not self.panel.session.muted)

    def setVoice_(self, sender):
        self.panel.session.set_voice(str(sender.representedObject()))

    def openConfig_(self, sender):
        import subprocess

        subprocess.run(["open", str(write_default_config())])

    def quit_(self, sender):
        self.panel.on_quit()


class Panel:
    def __init__(self, session, on_quit):
        self.session = session
        self.on_quit = on_quit
        self.state = "loading"
        self.expanded = False
        self._text = ""
        self.actions = MenuActions.alloc().initWithPanel_(self)

        x, y = self._load_position()
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H), style, NSBackingStoreBuffered, False)
        w = self.window
        w.setLevel_(NSStatusWindowLevel)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(True)
        w.setHidesOnDeactivate_(False)
        w.setMovableByWindowBackground_(True)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | NSWindowCollectionBehaviorStationary)
        content = w.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setCornerRadius_(H / 2)
        layer.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.11, 0.92).CGColor())

        self.mic = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.speaker = PillButton.alloc().initWithFrame_(NSMakeRect(PAD * 2 + BTN, PAD, BTN, BTN))
        self.cancel_btn = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.ok_btn = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.preview = NSTextField.labelWithString_("")
        self.preview.setFont_(NSFont.systemFontOfSize_(13))
        self.preview.setTextColor_(WHITE)
        self.preview.setLineBreakMode_(NSLineBreakByWordWrapping)
        self.preview.setMaximumNumberOfLines_(3)
        self.preview.cell().setWraps_(True)
        for v in (self.mic, self.speaker, self.cancel_btn, self.ok_btn, self.preview):
            content.addSubview_(v)
        self.cancel_btn.set_look("xmark", GREY)
        self.ok_btn.set_look("checkmark", GREEN)
        for v in (self.cancel_btn, self.ok_btn, self.preview):
            v.setHidden_(True)

        self.mic.on_click = self._mic_clicked
        self.speaker.on_click = self._speaker_clicked
        self.cancel_btn.on_click = lambda: self.session.cancel_dictation()
        self.ok_btn.on_click = lambda: self.session.finish_dictation()
        for v in (self.mic, self.speaker, self.cancel_btn, self.ok_btn):
            v.on_menu = self._show_menu
        self.apply_state("loading", "")
        w.orderFrontRegardless()

    # -- state --

    def apply_state(self, state: str, detail: str) -> None:
        self.state = state
        mic_sym, mic_tint, spk_sym, spk_tint = LOOKS.get(state, LOOKS["idle"])
        if self.session.muted and state not in ("open", "hearing", "ptt", "transcribing", "review", "dictating", "dict_hearing"):
            spk_sym, spk_tint = "speaker.slash.fill", GREY
        self.mic.set_look(mic_sym, mic_tint)
        self.speaker.set_look(spk_sym, spk_tint)
        self.mic.setToolTip_(detail or state)
        self.speaker.setToolTip_("Stop speaking" if state == "speaking" else "Replay the last reply")
        if self.expanded:
            self._refresh_preview()

    def show_preview(self, text) -> None:
        """Live dictation text; None collapses the pill back to two buttons."""
        if text is None:
            if self.expanded:
                self._collapse()
            return
        self._text = text
        if not self.expanded:
            self._expand()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        shown = self._text
        if len(shown) > PREVIEW_CHARS:
            shown = "…" + shown[-PREVIEW_CHARS:]
        dot = "● " if self.state == "dict_hearing" else "○ "
        self.preview.setStringValue_(dot + (shown or "Listening… speak, pause, and sentences appear here"))
        size = self.preview.cell().cellSizeForBounds_(NSMakeRect(0, 0, PREVIEW_W, 1000))
        text_h = min(max(float(size.height), 20.0), 60.0)
        self._layout(expanded=True, text_h=text_h)

    def _expand(self) -> None:
        self.expanded = True
        for v in (self.mic, self.speaker):
            v.setHidden_(True)
        for v in (self.cancel_btn, self.ok_btn, self.preview):
            v.setHidden_(False)

    def _collapse(self) -> None:
        self.expanded = False
        self._text = ""
        for v in (self.cancel_btn, self.ok_btn, self.preview):
            v.setHidden_(True)
        for v in (self.mic, self.speaker):
            v.setHidden_(False)
        self._layout(expanded=False)

    def _layout(self, expanded: bool, text_h: float = 20.0) -> None:
        new_w = W_EXPANDED if expanded else W
        new_h = max(H, text_h + PAD * 2) if expanded else H
        f = self.window.frame()
        screen_mid = NSScreen.mainScreen().frame().size.width / 2
        anchored_right = (f.origin.x + f.size.width / 2) > screen_mid
        x = f.origin.x + f.size.width - new_w if anchored_right else f.origin.x
        self.window.setFrame_display_(NSMakeRect(x, f.origin.y, new_w, new_h), True)
        self.window.contentView().layer().setCornerRadius_(min(new_h, H) / 2)
        if expanded:
            self.cancel_btn.setFrame_(NSMakeRect(PAD, (new_h - BTN) / 2, BTN, BTN))
            self.preview.setFrame_(NSMakeRect(PAD * 2 + BTN, (new_h - text_h) / 2, PREVIEW_W, text_h))
            self.ok_btn.setFrame_(NSMakeRect(PAD * 3 + BTN + PREVIEW_W, (new_h - BTN) / 2, BTN, BTN))
        else:
            self.mic.setFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
            self.speaker.setFrame_(NSMakeRect(PAD * 2 + BTN, PAD, BTN, BTN))

    # -- clicks --

    def _mic_clicked(self):
        self.session.talk_now()

    def _speaker_clicked(self):
        if self.state == "speaking":
            self.session.stop_speaking()
        else:
            self.session.replay_last()

    def _show_menu(self, view):
        from voicechat.tts import PREDEFINED_VOICES

        s = self.session
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        def add(title, action, state=None):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self.actions)
            if state is not None:
                item.setState_(1 if state else 0)
            menu.addItem_(item)
            return item

        add("Hands-free: mic opens after each reply", b"toggleHandsFree:", s.hands_free)
        add("Auto-send: press Enter for me", b"toggleAutoSend:", s.auto_submit)
        add("Mute the voice", b"toggleMute:", s.muted)
        menu.addItem_(NSMenuItem.separatorItem())
        voices = NSMenu.alloc().init()
        for name in PREDEFINED_VOICES:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(name, b"setVoice:", "")
            item.setTarget_(self.actions)
            item.setRepresentedObject_(name)
            voices.addItem_(item)
        voice_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Voice", None, "")
        voice_item.setSubmenu_(voices)
        menu.addItem_(voice_item)
        add("Open config file", b"openConfig:")
        menu.addItem_(NSMenuItem.separatorItem())
        add("Quit voicechat", b"quit:")
        menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), view)

    # -- position --

    def _load_position(self) -> tuple[float, float]:
        try:
            data = json.loads(POS_PATH.read_text())
            return float(data["x"]), float(data["y"])
        except Exception:
            frame = NSScreen.mainScreen().visibleFrame()
            return frame.origin.x + frame.size.width - W - 24, frame.origin.y + 24

    def save_position(self) -> None:
        try:
            f = self.window.frame()
            x = f.origin.x
            if self.expanded:  # store where the collapsed pill would sit
                screen_mid = NSScreen.mainScreen().frame().size.width / 2
                if (f.origin.x + f.size.width / 2) > screen_mid:
                    x = f.origin.x + f.size.width - W
            HOME_DIR.mkdir(parents=True, exist_ok=True)
            POS_PATH.write_text(json.dumps({"x": x, "y": f.origin.y}))
        except Exception:
            pass
