"""A small floating control: a mic and a speaker button, always on top, never steals focus.

Click the mic to start a dictation session: the pill widens into waveform · live text · ✕ · ✓.
Click the speaker to stop the voice, or to replay the last reply when it is quiet.
Right-click, or press and hold, for the options menu. Drag it anywhere; the spot is remembered.

Looks: a 36-point dark glass capsule with one accent colour. The accent means "live": the
waveform while the mic listens, the speaker while the voice talks. Everything else is grey. When text shows, the capsule becomes a rounded rectangle so words never
run into the curve, and the text is one line that scrolls, newest words at the right.
"""

from __future__ import annotations

import json
import os
import time

import objc
from AppKit import (
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSCompositingOperationSourceOver,
    NSFont,
    NSFontAttributeName,
    NSFontWeightMedium,
    NSForegroundColorAttributeName,
    NSGraphicsContext,
    NSImage,
    NSImageSymbolConfiguration,
    NSMenu,
    NSMenuItem,
    NSMutableAttributedString,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from Foundation import NSMakePoint, NSMakeRect, NSObject, NSTimer, NSZeroRect
from Quartz import (
    CGColorSpaceCreateDeviceRGB,
    CGContextDrawLinearGradient,
    CGContextSetBlendMode,
    CGGradientCreateWithColorComponents,
    CGPointMake,
    kCGBlendModeDestinationOut,
)

from voicechat.config import HOME_DIR, accent_rgb, write_default_config

POS_PATH = HOME_DIR / "panel.json"
BTN = 28  # a button's hit area
ICON = 13  # symbol point size
PAD = 4
H = BTN + PAD * 2  # 36
TEXT_W = 280
BARS_W = 18  # the waveform: 5 bars of 2 pt with 2 pt gaps
RADIUS_TEXT = 10.0  # corners while text shows; a capsule otherwise
FADE_W = 18.0  # how much of a clipped line fades out at the edge
W = BTN * 2 + PAD * 3
W_DICTATION = PAD * 6 + BARS_W + TEXT_W + BTN * 3  # waveform · text · ✕ · ✓ · speaker
W_SPEAKING = PAD * 4 + BTN * 2 + TEXT_W  # mic · sentence · speaker
LONG_PRESS_S = 0.45
TICK_S = 0.05
N_BARS = 5

WHITE = NSColor.whiteColor()
GREY = NSColor.colorWithWhite_alpha_(0.70, 1.0)
DIM = NSColor.colorWithWhite_alpha_(0.45, 1.0)
FONT = NSFont.systemFontOfSize_(12.5)

LISTENING = {"open", "hearing", "ptt", "dictating", "dict_hearing"}
# state -> (mic symbol, mic tint, speaker symbol, speaker tint); tints are grey | dim | white | accent
# Exactly one thing is coral at any time, and it is the thing to tap next: the mic at rest, the stop
# button while the voice speaks, the waveform while the mic listens. Muted or loading: all grey.
LOOKS = {
    "loading": ("mic.fill", "dim", "speaker.wave.2.fill", "dim"),
    "idle": ("mic.fill", "accent", "play.fill", "grey"),
    "your_turn": ("mic.fill", "accent", "play.fill", "grey"),
    "speaking": ("mic.fill", "grey", "stop.fill", "accent"),
    "open": ("mic.fill", "accent", "play.fill", "grey"),
    "hearing": ("mic.fill", "accent", "play.fill", "grey"),
    "ptt": ("mic.fill", "accent", "play.fill", "grey"),
    "dictating": ("mic.fill", "accent", "play.fill", "grey"),
    "dict_hearing": ("mic.fill", "accent", "play.fill", "grey"),
    "transcribing": ("mic.fill", "grey", "play.fill", "grey"),
    "review": ("mic.fill", "accent", "play.fill", "grey"),
    "muted": ("mic.fill", "grey", "speaker.slash.fill", "grey"),
}


class PillButton(NSView):
    """An SF Symbol that acts as a button, with long-press and right-click for a menu and drag-to-move."""

    def initWithFrame_(self, frame):
        self = objc.super(PillButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self.image = None
        self.tint = GREY
        self.icon_hidden = False  # the waveform takes the mic's place while it listens
        self.on_click = None
        self.on_menu = None
        self._timer = None
        self._long_fired = False
        self._down_at = None
        self._dragging = False
        return self

    def acceptsFirstMouse_(self, event):
        return True  # clicks work even though our app is never the active one

    @objc.python_method
    def set_look(self, symbol: str, tint) -> None:
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, symbol)
        if image is not None:  # size and colour baked into the symbol: it draws as-is
            conf = NSImageSymbolConfiguration.configurationWithPointSize_weight_(ICON, NSFontWeightMedium)
            conf = conf.configurationByApplyingConfiguration_(
                NSImageSymbolConfiguration.configurationWithHierarchicalColor_(tint))
            image = image.imageWithSymbolConfiguration_(conf) or image
        self.image = image
        self.tint = tint
        self.setNeedsDisplay_(True)

    @objc.python_method
    def set_icon_hidden(self, hidden: bool) -> None:
        if hidden != self.icon_hidden:
            self.icon_hidden = hidden
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        if self.image is None or self.icon_hidden:
            return
        size = self.image.size()
        b = self.bounds()
        r = NSMakeRect(round((b.size.width - size.width) / 2), round((b.size.height - size.height) / 2),
                       size.width, size.height)
        self.image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
            r, NSZeroRect, NSCompositingOperationSourceOver, 1.0, True, None)

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


class LevelBars(NSView):
    """Five thin bars that bounce with the microphone level: the 'live' light while the mic is open."""

    def initWithFrame_(self, frame):
        self = objc.super(LevelBars, self).initWithFrame_(frame)
        if self is None:
            return None
        self.levels = [0.0] * N_BARS
        self.color = GREY
        self._pushed_at = 0.0
        self.setWantsLayer_(True)
        return self

    def hitTest_(self, point):
        return None  # clicks fall through to the button underneath

    @objc.python_method
    def push(self, level: float) -> None:
        self.levels = self.levels[1:] + [max(0.0, min(1.0, float(level)))]
        self._pushed_at = time.monotonic()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def decay(self) -> None:
        """Called on the tick: when no level arrived for a while, let the bars settle."""
        if time.monotonic() - self._pushed_at > 0.12 and any(v > 0.01 for v in self.levels):
            self.push(self.levels[-1] * 0.5)

    @objc.python_method
    def reset(self) -> None:
        self.levels = [0.0] * N_BARS
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        b = self.bounds()
        bar_w = 2.0
        gap = (b.size.width - N_BARS * bar_w) / max(1, N_BARS - 1)
        min_h, max_h = 3.0, min(16.0, b.size.height - 4)
        self.color.set()
        for i, level in enumerate(self.levels):
            h = min_h + (max_h - min_h) * level
            x = i * (bar_w + gap)
            y = (b.size.height - h) / 2
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, bar_w, h), 1.0, 1.0).fill()


class ScrollLine(NSView):
    """One line of attributed text, clipped to its box. When the text is wider than the box it
    slides left so the anchor (the newest word, or the word being spoken) stays in view, and the
    clipped edge fades out instead of cutting letters in half."""

    def initWithFrame_(self, frame):
        self = objc.super(ScrollLine, self).initWithFrame_(frame)
        if self is None:
            return None
        self.attr = None
        self.anchor = None  # x in text coordinates to keep in view; None keeps the end in view
        self.setWantsLayer_(True)
        self.setClipsToBounds_(True)  # macOS 14+ stopped clipping by default
        return self

    def hitTest_(self, point):
        return None  # dragging the text moves the window, like the rest of the background

    @objc.python_method
    def set_text(self, attr, anchor: float | None = None) -> None:
        self.attr = attr
        self.anchor = anchor
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        if self.attr is None:
            return
        b = self.bounds()
        vw = b.size.width
        size = self.attr.size()
        tw = size.width
        if tw <= vw:
            offset = 0.0
        else:
            anchor = tw if self.anchor is None else self.anchor
            offset = max(vw - tw, min(0.0, vw * 0.72 - anchor))  # keep the anchor around 72% across
        fade_left = offset < -0.5
        fade_right = offset + tw > vw + 0.5
        # Draw into an image of our own first: fading means erasing towards the edge, and erasing
        # must not touch the glass behind us.
        img = NSImage.alloc().initWithSize_(b.size)
        img.lockFocus()
        self.attr.drawAtPoint_(NSMakePoint(offset, (b.size.height - size.height) / 2))
        if fade_left or fade_right:
            ctx = NSGraphicsContext.currentContext().CGContext()
            CGContextSetBlendMode(ctx, kCGBlendModeDestinationOut)
            gradient = CGGradientCreateWithColorComponents(
                CGColorSpaceCreateDeviceRGB(), [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0], [0.0, 1.0], 2)
            if fade_left:
                CGContextDrawLinearGradient(ctx, gradient, CGPointMake(0, 0), CGPointMake(FADE_W, 0), 0)
            if fade_right:
                CGContextDrawLinearGradient(ctx, gradient, CGPointMake(vw, 0), CGPointMake(vw - FADE_W, 0), 0)
        img.unlockFocus()
        img.drawInRect_fromRect_operation_fraction_(b, NSZeroRect, NSCompositingOperationSourceOver, 1.0)


class MenuActions(NSObject):
    """Target for the options menu and the timer; forwards to the session and the panel."""

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

        subprocess.run(["open", "-t", str(write_default_config())])  # .toml has no default app

    def quit_(self, sender):
        self.panel.on_quit()

    def hidePill_(self, sender):
        self.panel.set_hidden(True)

    def toggleHighlight_(self, sender):
        self.panel.session.set_highlight(not self.panel.session.highlight_enabled)

    def tick_(self, timer):
        self.panel._tick()


def _attr(piece: str, color) -> NSMutableAttributedString:
    return NSMutableAttributedString.alloc().initWithString_attributes_(
        piece, {NSFontAttributeName: FONT, NSForegroundColorAttributeName: color})


class Panel:
    def __init__(self, session, on_quit):
        self.session = session
        self.on_quit = on_quit
        self.state = "loading"
        self.mode = "collapsed"  # collapsed | dictation | speaking
        self._text = ""
        self._tail = ""
        self._speak_text = ""
        self._speak_t0 = 0.0
        self._speak_est = 1.0
        self._timer = None
        self.hidden = False
        self.on_visibility = None  # called with (hidden) so the menu bar item can say Show/Hide
        self.actions = MenuActions.alloc().initWithPanel_(self)
        r, g, b = accent_rgb(getattr(getattr(session, "cfg", None), "accent", "#E8735A"))
        self.accent = NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)

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
        w.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | NSWindowCollectionBehaviorStationary)

        glass = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        glass.setMaterial_(NSVisualEffectMaterialHUDWindow)
        glass.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        glass.setState_(NSVisualEffectStateActive)  # we are never the key window; look awake anyway
        glass.setWantsLayer_(True)
        layer = glass.layer()
        layer.setCornerRadius_(H / 2)
        layer.setMasksToBounds_(True)
        layer.setBorderWidth_(0.5)
        layer.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.16).CGColor())
        w.setContentView_(glass)
        self.content = glass
        tint = NSView.alloc().initWithFrame_(glass.bounds())  # deepen the glass a little for contrast
        tint.setWantsLayer_(True)
        tint.layer().setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.0, 0.45).CGColor())
        tint.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        glass.addSubview_(tint)

        self.mic = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.speaker = PillButton.alloc().initWithFrame_(NSMakeRect(PAD * 2 + BTN, PAD, BTN, BTN))
        self.cancel_btn = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.ok_btn = PillButton.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
        self.bars = LevelBars.alloc().initWithFrame_(NSMakeRect(PAD, PAD, BARS_W, BTN))
        self.line = ScrollLine.alloc().initWithFrame_(NSMakeRect(PAD, PAD, TEXT_W, BTN))
        for v in (self.mic, self.speaker, self.cancel_btn, self.ok_btn, self.line, self.bars):
            glass.addSubview_(v)
        self.cancel_btn.set_look("xmark", GREY)
        self.ok_btn.set_look("checkmark", WHITE)

        self.mic.on_click = self._mic_clicked
        self.speaker.on_click = self._speaker_clicked
        self.cancel_btn.on_click = lambda: self.session.cancel_dictation()
        self.ok_btn.on_click = lambda: self.session.finish_dictation()
        for v in (self.mic, self.speaker, self.cancel_btn, self.ok_btn):
            v.on_menu = self._show_menu
        self.apply_state("loading", "")
        w.orderFrontRegardless()

    # -- state --

    def _color(self, token: str):
        return {"grey": GREY, "dim": DIM, "white": WHITE, "accent": self.accent}[token]

    def apply_state(self, state: str, detail: str) -> None:
        self.state = state
        mic_sym, mic_tint, spk_sym, spk_tint = LOOKS.get(state, LOOKS["idle"])
        if self.session.muted and state not in LISTENING and state not in ("transcribing", "review"):
            spk_sym, spk_tint = "speaker.slash.fill", "grey"
        self.mic.set_look(mic_sym, self._color(mic_tint))
        self.speaker.set_look(spk_sym, self._color(spk_tint))
        self.mic.setToolTip_(detail or state)
        self.speaker.setToolTip_("Stop speaking" if state == "speaking" else "Read the selected text, or replay the last reply")
        self.bars.color = self.accent if state in LISTENING else DIM
        if state not in LISTENING:
            self.bars.reset()
        if self.mode == "dictation":
            self._refresh_preview()
        else:
            self._layout(self.mode)
        self._ensure_timer()

    def set_level(self, level: float) -> None:
        if not self.bars.isHidden():
            self.bars.push(level)

    def show_preview(self, text, tail: str = "") -> None:
        """Live dictation text (committed sentences, plus the one still forming); None collapses the pill."""
        if text is None:
            if self.mode == "dictation":
                self._collapse()
            return
        self._text = text
        self._tail = tail or ""
        self.mode = "dictation"
        self._refresh_preview()

    def show_speaking(self, text, est_seconds: float = 0.0, index: int = 0, total: int = 0) -> None:
        """The sentence being read: white up to the word being said, grey after it; None collapses."""
        if text is None:
            if self.mode == "speaking":
                self._collapse()
            return
        if self.mode == "dictation":
            return  # you're dictating; don't take the pill away
        self._speak_text = text
        self._speak_t0 = time.monotonic()
        self._speak_est = max(float(est_seconds), 0.6)
        self.mode = "speaking"
        self._refresh_speaking()
        self._ensure_timer()

    def _refresh_speaking(self) -> None:
        if self.mode != "speaking":
            return
        words = self._speak_text.split()
        if not words:
            return
        frac = min(1.0, (time.monotonic() - self._speak_t0) / self._speak_est)
        cur = min(len(words) - 1, int(frac * len(words)))
        attr = NSMutableAttributedString.alloc().init()
        attr.appendAttributedString_(_attr(" ".join(words[:cur + 1]), WHITE))  # said so far, and being said
        anchor = attr.size().width
        if cur + 1 < len(words):
            attr.appendAttributedString_(_attr(" " + " ".join(words[cur + 1:]), GREY))  # still to come
        self.line.set_text(attr, anchor)
        self._layout("speaking")

    def _refresh_preview(self) -> None:
        attr = NSMutableAttributedString.alloc().init()
        if not self._text and not self._tail:
            attr.appendAttributedString_(_attr("Listening… pause, and your words appear here", GREY))
        else:
            if self._text:
                attr.appendAttributedString_(_attr(self._text, WHITE))
            if self._tail:
                attr.appendAttributedString_(_attr((" " if self._text else "") + self._tail, GREY))
        self.line.set_text(attr, None)  # newest words at the right
        self._layout("dictation")

    def _collapse(self) -> None:
        self.mode = "collapsed"
        self._text = ""
        self._tail = ""
        self.line.set_text(None)
        self._layout("collapsed")
        self._ensure_timer()

    def _layout(self, mode: str) -> None:
        """The right edge never moves, so the speaker button stays put while the pill grows leftwards."""
        new_w = {"dictation": W_DICTATION, "speaking": W_SPEAKING}.get(mode, W)
        f = self.window.frame()
        if abs(f.size.width - new_w) > 0.5 or abs(f.size.height - H) > 0.5:
            visible = NSScreen.mainScreen().visibleFrame()
            x = max(visible.origin.x, f.origin.x + f.size.width - new_w)
            self.window.setFrame_display_(NSMakeRect(x, f.origin.y, new_w, H), True)
        self.content.layer().setCornerRadius_(H / 2 if mode == "collapsed" else RADIUS_TEXT)
        listening = self.state in LISTENING
        dictation = mode == "dictation"
        speaking = mode == "speaking"
        self.cancel_btn.setHidden_(not dictation)
        self.ok_btn.setHidden_(not dictation)
        self.line.setHidden_(not (dictation or speaking))
        self.mic.setHidden_(dictation)  # the mic's side becomes ✕ ✓; the speaker stays put
        if dictation:
            x = PAD
            self.bars.setFrame_(NSMakeRect(x, PAD, BARS_W, BTN))
            x += BARS_W + PAD
            self.line.setFrame_(NSMakeRect(x, PAD, TEXT_W, BTN))
            x += TEXT_W + PAD
            self.cancel_btn.setFrame_(NSMakeRect(x, PAD, BTN, BTN))
            x += BTN + PAD
            self.ok_btn.setFrame_(NSMakeRect(x, PAD, BTN, BTN))
            x += BTN + PAD
            self.speaker.setFrame_(NSMakeRect(x, PAD, BTN, BTN))
            self.bars.setHidden_(False)
        elif speaking:
            self.mic.setFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
            self.line.setFrame_(NSMakeRect(PAD * 2 + BTN, PAD, TEXT_W, BTN))
            self.speaker.setFrame_(NSMakeRect(PAD * 3 + BTN + TEXT_W, PAD, BTN, BTN))
            self.bars.setHidden_(True)
            self.mic.set_icon_hidden(False)
        else:
            self.mic.setFrame_(NSMakeRect(PAD, PAD, BTN, BTN))
            self.speaker.setFrame_(NSMakeRect(PAD * 2 + BTN, PAD, BTN, BTN))
            # while the mic listens, the waveform takes its place
            self.bars.setFrame_(NSMakeRect(PAD + (BTN - BARS_W) / 2, PAD, BARS_W, BTN))
            self.bars.setHidden_(not listening)
            self.mic.set_icon_hidden(listening)
        self.window.invalidateShadow()

    # -- the tick: word progress while speaking, settling bars while listening --

    def _ensure_timer(self) -> None:
        need = self.mode == "speaking" or self.state in LISTENING
        if need and self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                TICK_S, self.actions, b"tick:", None, True)
        elif not need and self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def _tick(self) -> None:
        if self.mode == "speaking":
            self._refresh_speaking()
        if not self.bars.isHidden():
            self.bars.decay()
        self._ensure_timer()

    # -- clicks --

    def _mic_clicked(self):
        self.session.talk_now()

    def _speaker_clicked(self):
        if self.state == "speaking":
            self.session.stop_speaking()
        else:
            self.session.speak_selection_or_replay()

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
        add("Underline the sentence on the page", b"toggleHighlight:", s.highlight_enabled)
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
        add("Hide pill (Show pill is in the menu bar)", b"hidePill:")
        add("Open config file", b"openConfig:")
        menu.addItem_(NSMenuItem.separatorItem())
        add("Quit voicechat", b"quit:")
        # Showing a menu activates us; give focus back to whatever app had it afterwards.
        from voicechat.front import give_focus_to

        previous = NSWorkspace.sharedWorkspace().frontmostApplication()
        menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0, 0), view)
        if previous is not None and int(previous.processIdentifier()) != os.getpid():
            give_focus_to(int(previous.processIdentifier()), timeout_s=0.3)

    # -- position --

    def _load_position(self) -> tuple[float, float]:
        try:
            data = json.loads(POS_PATH.read_text())
            return float(data["x"]), float(data["y"])
        except Exception:
            frame = NSScreen.mainScreen().visibleFrame()
            return frame.origin.x + frame.size.width - W - 24, frame.origin.y + 24

    def set_hidden(self, hidden: bool) -> None:
        """Tuck the pill away (nothing else changes: the key, the voice and the menu bar keep working)."""
        self.hidden = hidden
        if hidden:
            self.window.orderOut_(None)
        else:
            self.window.orderFrontRegardless()
        if self.on_visibility is not None:
            self.on_visibility(hidden)

    def save_position(self) -> None:
        try:
            f = self.window.frame()
            x = f.origin.x + f.size.width - W  # where the collapsed pill sits: the right edge is fixed
            HOME_DIR.mkdir(parents=True, exist_ok=True)
            POS_PATH.write_text(json.dumps({"x": x, "y": f.origin.y}))
        except Exception:
            pass
