"""The macOS menu bar face of the listener: `softvoice app`.

One quiet waveform in the menu bar, the same in every state (the pill is where state shows).
Click it for Talk, Stop speaking, Mute and Hands-free. The engine is the same `Session` the
terminal uses.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import traceback

from softvoice.config import CHAT_APPS, Config, write_default_config

MENU_BAR_SYMBOL = "waveform"  # an SF Symbol, drawn as a template image so it matches the menu bar
MENU_BAR_POINTS = 15.0
DETAILS = {
    "loading": "Loading models…",
    "idle": "Idle. Tap the key or click Talk.",
    "your_turn": "Your turn. Tap the key or click Talk.",
    "speaking": "Speaking… tap the key to interrupt",
    "open": "Listening… speak now",
    "hearing": "Hearing you… pause to send",
    "ptt": "Recording… release to send",
    "transcribing": "Transcribing…",
    "review": "In your prompt. Edit if you like, then press Enter.",
    "dictating": "Dictating… Enter or ✓ when done, Esc or ✕ to discard",
    "dict_hearing": "Hearing you…",
    "muted": "Muted",
}


def menu_bar_image():
    """The status item's image: one monochrome symbol that follows the menu bar's appearance."""
    from AppKit import NSFontWeightMedium, NSImage, NSImageSymbolConfiguration

    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(MENU_BAR_SYMBOL, "softvoice")
    if image is None:
        return None
    conf = NSImageSymbolConfiguration.configurationWithPointSize_weight_(MENU_BAR_POINTS, NSFontWeightMedium)
    image = image.imageWithSymbolConfiguration_(conf)
    image.setTemplate_(True)
    return image


def run_app(cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool) -> int:
    import rumps
    from PyObjCTools import AppHelper

    from softvoice.ptt import Session
    from softvoice.panel import Panel

    class MenuBarUI:
        supports_overlay = True

        def __init__(self, app):
            self.app = app

        def log(self, msg: str) -> None:
            print(msg, flush=True)

        def state(self, state: str, detail: str = "") -> None:  # called from worker threads
            AppHelper.callAfter(self.app.apply_state, state, detail)

        def preview(self, text: str | None, tail: str = "") -> None:
            AppHelper.callAfter(self.app.apply_preview, text, tail)

        def run_on_main(self, fn) -> None:
            AppHelper.callAfter(fn)

        def now_speaking(self, text, est_seconds: float = 0.0, index: int = 0, total: int = 0) -> None:
            AppHelper.callAfter(self.app.apply_speaking, text, est_seconds, index, total)

        def level(self, level: float) -> None:  # from the audio thread, ~20 times a second
            AppHelper.callAfter(self.app.apply_level, level)

        def watch_changed(self, on: bool, apps: list[str]) -> None:  # the pill's menu may have changed them
            AppHelper.callAfter(self.app.apply_watch, on, apps)

    class App(rumps.App):
        def __init__(self):
            super().__init__("softvoice", title=None, quit_button=None)
            # rumps only takes icons from files; hand it the symbol image directly. It reads this
            # attribute when it creates the status item.
            self._icon_nsimage = menu_bar_image()
            self.session: Session | None = None
            self.panel = None
            self.status = rumps.MenuItem(DETAILS["loading"])  # no callback: a disabled status line
            self.talk = rumps.MenuItem("Talk", callback=self.on_talk)
            self.stop_item = rumps.MenuItem("Stop speaking", callback=self.on_stop)
            self.mute_item = rumps.MenuItem("Mute", callback=self.on_mute)
            self.hf_item = rumps.MenuItem("Hands-free", callback=self.on_hands_free)
            self.hf_item.state = 1 if hands_free else 0
            self.send_item = rumps.MenuItem("Auto-send", callback=self.on_auto_send)
            self.send_item.state = 1 if auto_submit else 0
            self.pill_item = rumps.MenuItem("Hide pill", callback=self.on_toggle_pill)
            # Chat apps without hooks: a master switch and one tick per known app, all saved to the config file.
            self.watch_item = rumps.MenuItem("Read chat replies aloud", callback=self.on_watch_chats)
            self.watch_item.state = 1 if cfg.watch_chats else 0
            self.watch_menu = rumps.MenuItem("Read replies from")
            self.watch_menu.add(self.watch_item)
            self.watch_menu.add(rumps.separator)
            self.watch_app_items: dict[str, rumps.MenuItem] = {}
            for name, bundle in CHAT_APPS:
                item = rumps.MenuItem(name, callback=lambda sender, b=bundle: self.on_watch_app(sender, b))
                item.state = 1 if bundle in cfg.watch_apps else 0
                self.watch_app_items[bundle] = item
                self.watch_menu.add(item)
            self.menu = [
                self.status, None,
                self.talk, self.stop_item, self.mute_item, self.hf_item, self.send_item, self.watch_menu, None,
                self.pill_item, rumps.MenuItem("Open config file", callback=self.on_config), None,
                rumps.MenuItem("Quit softvoice", callback=self.on_quit),
            ]
            if not cfg.panel:
                self.pill_item._menuitem.setHidden_(True)
            self.tick = rumps.Timer(self.on_tick, 0.5)  # lets Python see Ctrl+C while the Cocoa loop runs
            self.tick.start()

        def apply_state(self, state: str, detail: str) -> None:
            self.status.title = detail or DETAILS.get(state, state)
            if self.panel is not None:
                self.panel.apply_state(state, detail)

        def apply_speaking(self, text, est_seconds=0.0, index=0, total=0) -> None:
            if self.panel is not None:
                self.panel.show_speaking(text, est_seconds, index, total)

        def apply_preview(self, text, tail="") -> None:
            if self.panel is not None:
                self.panel.show_preview(text, tail)

        def apply_level(self, level: float) -> None:
            if self.panel is not None:
                self.panel.set_level(level)

        def make_panel(self):
            try:
                self.panel = Panel(self.session, on_quit=self.on_quit)
                self.panel.on_visibility = self.pill_visibility
                self.panel.apply_state(self.session.ui_state, "")
            except Exception as exc:
                print(f"floating panel unavailable: {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()

        def on_tick(self, _):
            pass

        def on_toggle_pill(self, _):
            if self.panel is not None:
                self.panel.set_hidden(not self.panel.hidden)

        def show_pill(self):  # a second `softvoice app` asked for it
            if self.panel is not None:
                self.panel.set_hidden(False)

        def pill_visibility(self, hidden: bool) -> None:
            self.pill_item.title = "Show pill" if hidden else "Hide pill"

        def on_talk(self, _):
            if self.session:
                self.session.talk_now()

        def on_stop(self, _):
            if self.session:
                self.session.stop_speaking()

        def on_mute(self, _):
            if self.session:
                muted = not self.session.muted
                self.session.set_muted(muted)
                self.mute_item.title = "Unmute" if muted else "Mute"

        def on_hands_free(self, sender):
            sender.state = 0 if sender.state else 1
            if self.session:
                self.session.set_hands_free(bool(sender.state))

        def on_auto_send(self, sender):
            sender.state = 0 if sender.state else 1
            if self.session:
                self.session.set_auto_submit(bool(sender.state))

        def on_watch_chats(self, sender):
            sender.state = 0 if sender.state else 1
            if self.session:
                self.session.set_watch_chats(bool(sender.state))

        def on_watch_app(self, sender, bundle: str):
            sender.state = 0 if sender.state else 1
            if self.session:
                self.session.set_watch_app(bundle, bool(sender.state))

        def apply_watch(self, on: bool, apps: list[str]) -> None:
            self.watch_item.state = 1 if on else 0
            for bundle, item in self.watch_app_items.items():
                item.state = 1 if bundle in apps else 0

        def on_config(self, _):
            subprocess.run(["open", "-t", str(write_default_config())])  # -t: the default text editor; .toml has no app

        def on_quit(self, _=None):
            if self.panel is not None:
                self.panel.save_position()
            if self.session:
                try:
                    self.session.stop()
                except Exception:
                    pass
            instance.release()
            rumps.quit_application()

    from softvoice import instance

    other = instance.claim()
    if other is not None:  # one copy is enough: show its pill and leave
        shown = other > 0 and instance.show(other)
        print("softvoice app is already running" + (": showing its pill." if shown else "."), flush=True)
        return 0

    app = App()
    ui = MenuBarUI(app)
    session = Session(cfg, hotkey, auto_submit, paste, hands_free, ui=ui)
    app.session = session

    # We live in the menu bar and the pill: no Dock icon, no app menu, and never the active app.
    # rumps activates us when its loop starts; that stole focus from the window you were typing in,
    # so pastes were refused and the underline had no window to read. Give focus straight back.
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    from softvoice.front import front_pid, give_focus_to

    launched_from = front_pid()
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def hand_back():
        if launched_from and launched_from != os.getpid():
            give_focus_to(launched_from, timeout_s=0.5)

    def hide_menu_bar_item():  # `menu_bar_icon = false`: the pill alone
        try:
            app._nsapp.nsstatusitem.setVisible_(False)
        except Exception as exc:
            print(f"could not hide the menu bar item: {exc}", file=sys.stderr, flush=True)

    def boot():
        try:
            session.start()
        except Exception as exc:
            print(f"softvoice app could not start: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
            AppHelper.callAfter(app.on_quit)

    # Python signal handlers run on the main thread between bytecodes; the 0.5 s rumps timer
    # above makes sure there are some while the Cocoa loop runs.
    signal.signal(signal.SIGINT, lambda *_: app.on_quit())
    signal.signal(signal.SIGTERM, lambda *_: app.on_quit())  # Quit from `autostart off`, launchctl, kill
    signal.signal(instance.SHOW_SIGNAL, lambda *_: AppHelper.callAfter(app.show_pill))
    threading.Thread(target=boot, name="boot", daemon=True).start()
    if cfg.panel:
        AppHelper.callAfter(app.make_panel)  # runs once the Cocoa loop is up
    AppHelper.callAfter(hand_back)
    if not cfg.menu_bar_icon:
        AppHelper.callAfter(hide_menu_bar_item)
    print("softvoice is running: floating panel (mic + speaker) and menu bar icon. Ctrl+C or Quit to stop.", flush=True)
    app.run()
    return 0
