"""The macOS menu bar face of the listener: `voicechat app`.

A mic in the menu bar shows whose turn it is. Click it for Talk, Stop speaking, Mute and
Hands-free. The engine is the same `Session` the terminal uses.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import traceback

from voicechat.config import Config, write_default_config

ICONS = {
    "loading": "⏳",
    "idle": "🎙",
    "your_turn": "🎙 your turn",
    "speaking": "🔊",
    "open": "🔴",
    "hearing": "🔴 …",
    "ptt": "🔴",
    "transcribing": "⏳",
    "review": "✏️",
    "dictating": "🔴",
    "dict_hearing": "🔴 …",
    "muted": "🔇",
}
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
    "dictating": "Dictating… ✓ when done, ✕ to discard",
    "dict_hearing": "Hearing you…",
    "muted": "Muted",
}


def run_app(cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool) -> int:
    import rumps
    from PyObjCTools import AppHelper

    from voicechat.ptt import Session
    from voicechat.panel import Panel

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

    class App(rumps.App):
        def __init__(self):
            super().__init__("voicechat", title=ICONS["loading"], quit_button=None)
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
            self.menu = [
                self.status, None,
                self.talk, self.stop_item, self.mute_item, self.hf_item, self.send_item, None,
                rumps.MenuItem("Open config file", callback=self.on_config),
                rumps.MenuItem("Quit voicechat", callback=self.on_quit),
            ]
            self.tick = rumps.Timer(self.on_tick, 0.5)  # lets Python see Ctrl+C while the Cocoa loop runs
            self.tick.start()

        def apply_state(self, state: str, detail: str) -> None:
            if cfg.menu_bar_icon:
                self.title = ICONS.get(state, ICONS["idle"])
            self.status.title = detail or DETAILS.get(state, state)
            if self.panel is not None:
                self.panel.apply_state(state, detail)

        def apply_speaking(self, text, est_seconds=0.0, index=0, total=0) -> None:
            if self.panel is not None:
                self.panel.show_speaking(text, est_seconds, index, total)

        def apply_preview(self, text, tail="") -> None:
            if self.panel is not None:
                self.panel.show_preview(text, tail)

        def make_panel(self):
            try:
                self.panel = Panel(self.session, on_quit=self.on_quit)
                self.panel.apply_state(self.session.ui_state, "")
            except Exception as exc:
                print(f"floating panel unavailable: {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()

        def on_tick(self, _):
            pass

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

        def on_config(self, _):
            subprocess.run(["open", str(write_default_config())])

        def on_quit(self, _=None):
            if self.panel is not None:
                self.panel.save_position()
            if self.session:
                try:
                    self.session.stop()
                except Exception:
                    pass
            rumps.quit_application()

    app = App()
    ui = MenuBarUI(app)
    session = Session(cfg, hotkey, auto_submit, paste, hands_free, ui=ui)
    app.session = session

    def boot():
        try:
            session.start()
        except Exception as exc:
            print(f"voicechat app could not start: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
            AppHelper.callAfter(app.on_quit)

    signal.signal(signal.SIGINT, lambda *_: app.on_quit())
    threading.Thread(target=boot, name="boot", daemon=True).start()
    if cfg.panel:
        AppHelper.callAfter(app.make_panel)  # runs once the Cocoa loop is up
    if not cfg.menu_bar_icon:
        app.title = ""
    print("voicechat is running: floating panel (mic + speaker) and menu bar icon. Ctrl+C or Quit to stop.", flush=True)
    app.run()
    return 0
