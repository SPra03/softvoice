"""Listening: push-to-talk, tap-to-talk, and hands-free turn-taking driven by the speaker daemon.

One engine (`Session`) with two faces: the terminal (`voicechat listen`) and the macOS menu bar
(`voicechat app`). Key gestures:

    hold the key        push-to-talk: record while held, transcribe on release
    tap the key         tap-to-talk: the mic opens, voice detection ends the take
    key while speaking  interrupt the speaker (and start recording)
    key during a take   send what you have said so far

Hands-free: when the daemon finishes speaking an agent's reply, the mic opens by itself.
Transcripts are pasted into the focused prompt. Hands-free and tap-to-talk paste only into
terminal/agent apps, or the app you last used push-to-talk in, and press Enter.
"""

from __future__ import annotations

import fnmatch
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

import numpy as np

from voicechat.config import Config, accent_rgb

RECORD_RATE = 16000


# -- small helpers ------------------------------------------------------------------

def is_tap(held_seconds: float, threshold_ms: int) -> bool:
    return held_seconds * 1000 < threshold_ms


def frontmost_app() -> tuple[str | None, str | None]:
    """(bundle id, name) of the app that has keyboard focus, or (None, None) if unknown."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier(), app.localizedName()
    except Exception:
        return None, None


def target_allowed(bundle: str | None, patterns: list[str], last_ptt_target: str | None) -> bool:
    if bundle is None:
        return True  # can't tell; trust the user
    if last_ptt_target and bundle == last_ptt_target:
        return True
    return any(fnmatch.fnmatch(bundle, pat) for pat in patterns)


def is_cancel(text: str, cancel_words: list[str]) -> bool:
    norm = " ".join(text.lower().replace(",", " ").split()).strip(" .!?")
    return norm in {w.lower() for w in cancel_words}


def strip_send_word(text: str, send_words: list[str]) -> tuple[str, bool]:
    """If the transcript ends with a send word ("... and fix it. Send it."), drop it and report True."""
    stripped = text.rstrip(" .!?,")
    low = stripped.lower()
    for word in sorted(send_words, key=len, reverse=True):
        w = word.lower().strip()
        if low == w:
            return "", True
        if low.endswith(" " + w) or low.endswith("," + w) or low.endswith(". " + w):
            cut = stripped[: len(stripped) - len(w)].rstrip(" ,.")
            return cut + ("." if cut and cut[-1] not in ".!?" else ""), True
    return text, False


def earcon(kind: str) -> None:
    """A short tone: higher when the mic opens, lower when it closes."""
    import sounddevice as sd

    sr = 24000
    freq, dur, amp = (880.0, 0.09, 0.2) if kind == "open" else (440.0, 0.07, 0.15)
    t = np.arange(int(sr * dur)) / sr
    tone = (amp * np.sin(2 * np.pi * freq * t) * np.hanning(len(t))).astype(np.float32)
    try:
        sd.play(tone, sr, blocking=True)
    except Exception:
        pass


def paste_text(text: str, submit: bool, delay_ms: int) -> None:
    from voicechat.hotkey import KEY_RETURN, KEY_V, press

    old = None
    if text:
        old = subprocess.run(["pbpaste"], capture_output=True).stdout
        subprocess.run(["pbcopy"], input=text.encode())
        time.sleep(delay_ms / 1000)
        press(KEY_V, cmd=True)
    if submit:
        time.sleep(0.15)
        press(KEY_RETURN)
    if old is not None:
        time.sleep(0.3)
        subprocess.run(["pbcopy"], input=old)  # give the clipboard back


def copy_selection() -> str:
    """Copy whatever is selected in the frontmost app and return it; "" when nothing is selected."""
    from voicechat.hotkey import KEY_C, press

    sentinel = "\u2063voicechat-no-selection\u2063"
    old = subprocess.run(["pbpaste"], capture_output=True).stdout
    subprocess.run(["pbcopy"], input=sentinel.encode())
    press(KEY_C, cmd=True)
    time.sleep(0.2)
    new = subprocess.run(["pbpaste"], capture_output=True).stdout
    subprocess.run(["pbcopy"], input=old)  # give the clipboard back
    text = new.decode("utf-8", errors="replace")
    return "" if text == sentinel else text


def _interrupt_speech(reason: str = "ptt") -> None:
    try:
        from voicechat.client import send

        send({"cmd": "stop", "reason": reason}, autostart=False, timeout=0.3)
    except Exception:
        pass


# -- microphone ---------------------------------------------------------------------

def level_of(block: np.ndarray) -> float:
    """Loudness of an audio block as 0..1: silence near 0, normal speech around 0.4-0.8."""
    if block.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
    db = 20.0 * np.log10(rms + 1e-6)
    return float(min(1.0, max(0.0, (db + 50.0) / 40.0)))


class Recorder:
    """Keeps the microphone open; buffers audio only while recording.
    `read_new` hands out fresh audio for live VAD, `stop` returns the whole take."""

    def __init__(self, rate: int = RECORD_RATE, on_level=None):
        import sounddevice as sd

        self.lock = threading.Lock()
        self.recording = False
        self.on_level = on_level  # called ~20 times a second with a 0..1 loudness while recording
        self._level_at = 0.0
        self.chunks: list[np.ndarray] = []
        self.live: queue.Queue[np.ndarray] = queue.Queue()
        try:
            self.stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", callback=self._cb)
            self.rate = rate
        except Exception:  # device refuses 16 kHz: use its default and resample later
            self.stream = sd.InputStream(channels=1, dtype="float32", callback=self._cb)
            self.rate = int(self.stream.samplerate)
        self.stream.start()

    def _cb(self, indata, frames, time_info, status):
        if self.recording:
            block = indata[:, 0].copy()
            with self.lock:
                self.chunks.append(block)
            self.live.put(block)
            now = time.monotonic()
            if self.on_level is not None and now - self._level_at >= 0.05:
                self._level_at = now
                try:
                    self.on_level(level_of(block))
                except Exception:
                    pass

    def start(self) -> None:
        with self.lock:
            self.chunks = []
            self.recording = True
        while not self.live.empty():
            self.live.get_nowait()

    def read_new(self, timeout: float = 0.05) -> np.ndarray:
        parts = []
        try:
            parts.append(self.live.get(timeout=timeout))
            while True:
                parts.append(self.live.get_nowait())
        except queue.Empty:
            pass
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def stop(self) -> np.ndarray:
        with self.lock:
            self.recording = False
            audio = np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype=np.float32)
            self.chunks = []
        return audio

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


# -- user interfaces ----------------------------------------------------------------

class TerminalUI:
    """Prints state changes; the default face of `voicechat listen`."""

    def __init__(self, hotkey: str):
        self.hotkey = hotkey

    def log(self, msg: str) -> None:
        print(msg, flush=True)

    def state(self, state: str, detail: str = "") -> None:
        line = {
            "open": "🎤 your turn ...",
            "hearing": "  ● hearing you ...",
            "ptt": "● listening ...",
            "your_turn": f"  your turn: tap {self.hotkey} to talk",
            "review": "  (in your prompt: edit if you like, then press Enter)",
            "dictating": f"🎙 dictating… tap {self.hotkey} when done",
            "muted": "  (muted)",
        }.get(state)
        if line:
            print(line, flush=True)

    def preview(self, text: str | None, tail: str = "") -> None:
        pass  # committed sentences are logged as they land

    def run_on_main(self, fn) -> None:
        fn()  # `voicechat listen` drives everything from the main thread already

    def now_speaking(self, text: str | None, est_seconds: float = 0.0, index: int = 0, total: int = 0) -> None:
        pass  # the terminal does not follow along

    def level(self, level: float) -> None:
        pass  # no waveform in the terminal


# -- the session --------------------------------------------------------------------

class Session:
    def __init__(self, cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool, ui=None):
        self.cfg = cfg
        self.hotkey = hotkey
        self.auto_submit = auto_submit
        self.paste = paste
        self.hands_free = hands_free
        self.ui = ui or TerminalUI(hotkey)
        self.ui_state = "loading"
        self.state = "idle"  # idle | ptt | auto | dictation
        self.state_lock = threading.Lock()
        self.closing = False
        self.auto_cancel = threading.Event()
        self.auto_finish = threading.Event()
        self.auto_done = threading.Event()
        self.auto_done.set()
        self.dict_finish = threading.Event()
        self.dict_cancel = threading.Event()
        self.last_dictation_text: str | None = None
        self.resume_after = False
        self.speaking = False
        self.muted = False
        self.last_ptt_target: str | None = None
        self.front = None  # FrontTracker: the last front app that is not us
        self.ptt_t0 = 0.0
        self.key: tuple[int, int | None] | None = None
        self.hotkey_tap = None
        self.highlighter = None
        self.highlight_enabled = cfg.highlight_on_page
        self.transcriber = None
        self.recorder: Recorder | None = None
        self.detector = None

    # -- lifecycle --

    def start(self) -> None:
        """Load models, open the mic, start the key watcher and the daemon event feed. Blocks a few seconds."""
        from voicechat.client import ensure_daemon
        from voicechat.hotkey import resolve_key
        from voicechat.permissions import check_and_request, input_monitoring
        from voicechat.stt import Transcriber
        from voicechat.vad import UtteranceDetector

        self.key = resolve_key(self.hotkey)
        self._ui("loading", "Loading models…")
        self.ui.log(f"loading {self.cfg.stt_model} ...")
        self.transcriber = Transcriber(self.cfg.stt_model)
        self.detector = UtteranceDetector(self.cfg.end_silence_ms)
        self.ui.log("starting the speaker daemon ...")
        if not ensure_daemon():
            raise RuntimeError("the speaker daemon did not start; see `voicechat log`")
        self.recorder = Recorder(on_level=self._on_level)
        self.ui.log(f"ready. Tap {self.hotkey} to talk, or hold it to talk while held. Ctrl+C to quit.")
        if self.hands_free:
            self.ui.log(f"hands-free: after each spoken reply the mic opens (beep). Pause {self.cfg.end_silence_ms / 1000:.1f}s "
                        f"to send; say \"{self.cfg.cancel_words[0]}\" to discard; silence for {self.cfg.listen_timeout_s:.0f}s closes the mic.")
        check_and_request(need_paste=self.paste, need_hotkey=True, out=self.ui.log)
        self.ui.log("Microphone: if nothing is ever heard, enable this terminal's app under Privacy & Security > Microphone.")
        if input_monitoring() in ("granted", "unavailable"):
            self._start_key_listener()
        else:  # start the key watcher the moment the permission is toggled on
            threading.Thread(target=self._wait_for_input_monitoring, daemon=True).start()
        try:
            from voicechat.front import FrontTracker

            self.front = FrontTracker()
            self.ui.run_on_main(self.front.install)
        except Exception as exc:
            self.ui.log(f"front-app tracking unavailable: {exc}")
        if getattr(self.ui, "supports_overlay", False):
            try:
                from voicechat.highlight import Highlighter

                self.highlighter = Highlighter(self.ui.run_on_main, accent_rgb(self.cfg.underline),
                                               other_pid=lambda: self.front.pid if self.front else None)
            except Exception as exc:
                self.ui.log(f"on-page highlight unavailable: {exc}")
        threading.Thread(target=self._event_loop, name="events", daemon=True).start()
        self._ui("idle")

    def wait(self) -> None:
        from voicechat.hotkey import run_main_loop_once

        try:
            while not self.closing:
                run_main_loop_once(0.25)  # the key tap is serviced by the main run loop
        except KeyboardInterrupt:
            print("\nbye", file=sys.stderr)
        finally:
            self.stop()

    def _on_level(self, level: float) -> None:
        fn = getattr(self.ui, "level", None)
        if fn is not None:
            fn(level)

    def stop(self) -> None:
        self.closing = True
        self.auto_cancel.set()
        if self.hotkey_tap is not None:
            self.ui.run_on_main(self.hotkey_tap.remove)
        if self.recorder:
            self.recorder.close()

    def run(self) -> int:
        self.start()
        self.wait()
        return 0

    # -- actions (menu bar, terminal) --

    def talk_now(self) -> None:
        """Open the mic now (the Talk button). During a take: send what was said so far."""
        with self.state_lock:
            st = self.state
        if st == "auto":
            self.auto_finish.set()
            return
        if st == "dictation":
            self.dict_finish.set()
            return
        if st == "ptt":
            return
        threading.Thread(target=_interrupt_speech, args=("menu",), daemon=True).start()
        self.start_dictation()

    def start_dictation(self, continue_recording: bool = False) -> None:
        """Open the mic and keep it open; sentences are committed to the preview as you pause."""
        if not self._set_state("dictation", expect="ptt" if continue_recording else "idle"):
            return
        self.dict_finish.clear()
        self.dict_cancel.clear()
        threading.Thread(target=self._dictation_loop, args=(continue_recording,), name="dictation", daemon=True).start()

    def finish_dictation(self) -> None:  # ✓
        self.dict_finish.set()

    def cancel_dictation(self) -> None:  # ✕
        self.dict_cancel.set()

    def stop_speaking(self) -> None:
        threading.Thread(target=_interrupt_speech, args=("menu",), daemon=True).start()

    def set_muted(self, muted: bool) -> None:
        from voicechat.client import send

        try:
            send({"cmd": "mute" if muted else "unmute"}, autostart=False, timeout=1.0)
        except Exception as exc:
            self.ui.log(f"could not reach the speaker daemon: {exc}")
        self.muted = muted
        self.ui.log("muted" if muted else "unmuted")
        self._ui("muted" if muted else "idle")

    def set_hands_free(self, on: bool) -> None:
        self.hands_free = on
        self.ui.log(f"hands-free {'on' if on else 'off'}")

    def replay_last(self) -> None:
        from voicechat.client import send

        try:
            resp = send({"cmd": "replay"}, autostart=False, timeout=1.0)
            if resp.get("skipped"):
                self.ui.log("nothing to replay yet")
        except Exception as exc:
            self.ui.log(f"could not reach the speaker daemon: {exc}")

    def speak_selection_or_replay(self) -> None:
        """The play button: read the text selected in the front app, or replay the last reply."""
        from voicechat.client import send

        text = copy_selection() if self.paste else ""
        if text.strip():
            try:
                send({"cmd": "speak", "text": text, "meta": {"event": "selection", "session_id": "selection"}})
                self.ui.log(f"speaking the selected text ({len(text)} chars)")
            except Exception as exc:
                self.ui.log(f"could not reach the speaker daemon: {exc}")
            if self.cfg.clear_selection:
                threading.Thread(target=self._clear_selection, daemon=True).start()
            return
        self.replay_last()

    def _clear_selection(self) -> None:
        """Drop the selection we just read, so the underline is what you see instead of the blue."""
        from voicechat.front import front_pid
        from voicechat.selection import clear_selection

        try:
            result = clear_selection(front_pid())
        except Exception as exc:
            result = f"failed: {type(exc).__name__}: {exc}"
        if result != "collapsed":
            self.ui.log(f"  (selection not cleared: {result})")

    def set_voice(self, name: str) -> None:
        from voicechat.client import send

        try:
            resp = send({"cmd": "voice", "voice": name}, autostart=False, timeout=30.0)
            self.ui.log(f"voice: {name}" if resp.get("ok") else f"voice change failed: {resp.get('error')}")
        except Exception as exc:
            self.ui.log(f"could not reach the speaker daemon: {exc}")

    def set_highlight(self, on: bool) -> None:
        self.highlight_enabled = on
        if not on and self.highlighter:
            self.highlighter.hide()
        self.ui.log(f"on-page highlight {'on' if on else 'off'}")

    def set_auto_submit(self, on: bool) -> None:
        self.auto_submit = on
        self.ui.log("auto-send on: takes are sent as soon as they are pasted" if on
                    else "auto-send off: takes wait in your prompt until you press Enter, or end with \"send it\"")

    # -- internals --

    def _ui(self, state: str, detail: str = "") -> None:
        self.ui_state = state
        self.ui.state(state, detail)

    def _set_state(self, new: str, expect: str | None = None) -> bool:
        with self.state_lock:
            if expect is not None and self.state != expect:
                return False
            self.state = new
            return True

    def _start_key_listener(self) -> None:
        from voicechat.hotkey import Hotkey

        keycode, flag = self.key
        self.hotkey_tap = Hotkey(keycode, flag, self._on_press, self._on_release, on_scroll=self._on_scroll)

        def install():
            if not self.hotkey_tap.install():
                self.ui.log("could not watch the key: Input Monitoring is not granted for this terminal's app")

        self.ui.run_on_main(install)  # the tap lives on the main run loop

    def _on_scroll(self) -> None:  # main thread, on every scroll event: just a flag for the underline
        if self.highlighter is not None:
            self.highlighter.nudge()

    def _wait_for_input_monitoring(self) -> None:
        from voicechat.permissions import input_monitoring

        while not self.closing:
            time.sleep(2.0)
            if input_monitoring() == "granted":
                self._start_key_listener()
                self.ui.log(f"Input Monitoring granted: tap or hold {self.hotkey} to talk.")
                return

    # -- the key --

    def _on_press(self) -> None:
        with self.state_lock:
            st = self.state
        if st == "ptt":
            return  # key repeat while held
        if st == "auto":
            self.auto_finish.set()  # "I'm done": send what was said so far
            return
        if st == "dictation":
            self.dict_finish.set()  # tap again = ✓
            return
        threading.Thread(target=_interrupt_speech, args=("ptt",), daemon=True).start()
        if not self._set_state("ptt", expect="idle"):
            return
        self.ptt_t0 = time.monotonic()
        self.recorder.start()
        self._ui("ptt", "Recording… release to send, or let go now to keep talking")

    def _on_release(self) -> None:
        with self.state_lock:
            if self.state != "ptt":
                return
            held = time.monotonic() - self.ptt_t0
            if is_tap(held, self.cfg.tap_threshold_ms):  # a tap: keep recording as a dictation session
                self.state = "dictation"
                self.dict_finish.clear()
                self.dict_cancel.clear()
                threading.Thread(target=self._dictation_loop, args=(True,), name="dictation", daemon=True).start()
                return
        threading.Thread(target=self._finish_ptt, daemon=True).start()

    def _finish_ptt(self) -> None:
        try:
            audio = self.recorder.stop()
            held = time.monotonic() - self.ptt_t0
            self._ui("transcribing", "Transcribing…")
            text, dt = self._transcribe(audio)
            if not text:
                self.ui.log(f"  (heard nothing, {held:.1f}s)")
                return
            self.ui.log(f"  {text}   [{held:.1f}s speech, {dt:.2f}s transcribe]")
            text, say_send = strip_send_word(text, self.cfg.send_words)
            if self.paste and text:
                submit = self.auto_submit or say_send
                if self._deliver(text, submit, anywhere=True):  # you held the key in that window: it is the target
                    self.ui.log("  → sent" if submit else "  → pasted; press Enter to send")
        except Exception as exc:
            self.ui.log(f"  push-to-talk error: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self._set_state("idle")
            self._ui("speaking" if self.speaking else "idle")

    # -- the daemon's events --

    def _event_loop(self) -> None:
        from voicechat.client import ensure_daemon, subscribe

        while not self.closing:
            try:
                ensure_daemon()
                for ev in subscribe():
                    if self.closing:
                        return
                    if ev.get("subscribed"):
                        status = ev.get("status") or {}
                        self.muted = bool(status.get("muted"))
                        if status.get("speaking"):
                            self.speaking = True
                            self._ui("speaking", "Speaking…")
                        continue
                    self._on_event(ev)
            except Exception:
                pass
            time.sleep(2.0)  # daemon gone; come back when it is

    def _on_event(self, ev: dict) -> None:
        kind = ev.get("event")
        project = ev.get("project")
        if kind == "speech_start":
            self.speaking = True
            with self.state_lock:
                in_auto = self.state == "auto"
                if self.state == "dictation":
                    return  # you're dictating; the speaker's state is not shown
            if in_auto:  # don't record the speaker; pick the turn up again afterwards
                self.resume_after = True
                self.auto_cancel.set()
            elif self.state == "idle":
                self._ui("speaking", f"Speaking{f' ({project})' if project else ''}… tap {self.hotkey} to interrupt")
            if self.highlighter and self.highlight_enabled:
                self.highlighter.begin()
        elif kind == "sentence":
            if self.state == "dictation":
                return
            text = str(ev.get("text") or "")
            self.ui.now_speaking(text, float(ev.get("est_seconds") or 0.0), int(ev.get("index") or 0), int(ev.get("total") or 1))
            if self.highlighter and self.highlight_enabled:
                self.highlighter.show_for(text)
        elif kind == "speech_end":
            self.speaking = False
            self.ui.now_speaking(None)
            if self.highlighter:
                self.highlighter.hide()
            if ev.get("interrupted"):
                self.resume_after = False  # you typed, or you're already talking
                if self.state == "idle":
                    self._ui("idle")
                return
            if ev.get("source") == "Stop" or self.resume_after:
                self.resume_after = False
                if self.hands_free and not self.muted:
                    self._start_auto()
                else:
                    self._ui("your_turn")
            elif self.state == "idle":
                self._ui("idle")
        elif kind == "daemon_quit":
            self.speaking = False
            if self.state == "idle":
                self._ui("idle", "Speaker daemon stopped")

    # -- taking a turn --

    def _start_auto(self) -> None:
        if not self._set_state("auto", expect="idle"):
            return
        self.auto_cancel.clear()
        self.auto_finish.clear()
        self.auto_done.clear()
        threading.Thread(target=self._auto_listen, name="auto-listen", daemon=True).start()

    def _auto_listen(self, continue_recording: bool = False) -> None:
        cfg = self.cfg
        end_state = "idle"
        try:
            for attempt in range(2):  # a take with no words gets one more chance
                text = self._take(continue_recording and attempt == 0)
                if text is None:  # cancelled, timed out, or failed: the turn is over
                    end_state = "speaking" if self.resume_after or self.speaking else ("your_turn" if self.timed_out else "idle")
                    return
                if text:
                    break
                if attempt == 0:
                    self.ui.log("  (heard a sound but no words; listening again)")
            else:
                self.ui.log("  (heard nothing)")
                end_state = "your_turn"
                return
            if is_cancel(text, cfg.cancel_words):
                self.ui.log(f"  \"{text}\" — discarded")
                end_state = "your_turn"
                return
            text, say_send = strip_send_word(text, cfg.send_words)
            if not text:  # just "send it": press Enter on whatever is already in the prompt
                if self.paste and self._deliver("", submit=True):
                    self.ui.log("  → sent what was in the prompt")
                return
            if not self.paste:
                return
            submit = self.auto_submit or say_send
            if not self._deliver(text, submit):
                end_state = "your_turn"
                return
            if submit:
                self.ui.log("  → sent")
            else:
                self.ui.log("  → pasted; press Enter to send, or say \"send it\" at the end next time")
                end_state = "review"
        except Exception as exc:
            self.ui.log(f"  hands-free error: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self._set_state("idle")
            self._ui(end_state, "Sent. Waiting for the reply…" if end_state == "idle" else "")
            self.auto_done.set()

    def _take(self, continue_recording: bool = False) -> str | None:
        """Open the mic (or keep the current recording), wait for one utterance, transcribe it.
        Returns the text ("" when speech was detected but no words came out), or None when the
        take was cancelled or nobody spoke."""
        cfg = self.cfg
        self.timed_out = False
        if not continue_recording:
            if cfg.earcon:
                earcon("open")
            self.recorder.start()
        self.detector.reset()
        t_open = time.monotonic()
        started_at: float | None = None
        self._ui("open", "Listening… speak now")
        while True:
            if self.auto_cancel.is_set() or self.closing:
                self.recorder.stop()
                self.ui.log("  (take cancelled)")
                return None
            if self.auto_finish.is_set():
                if started_at is None:  # tapped again before saying anything: never mind
                    self.recorder.stop()
                    self.ui.log("  (take cancelled)")
                    return None
                break
            new = self.recorder.read_new(0.05)
            now = time.monotonic()
            if new.size:
                if self.recorder.rate != RECORD_RATE:
                    import soxr

                    new = soxr.resample(new, self.recorder.rate, RECORD_RATE)
                ev = self.detector.feed(new)
                if ev == "start":
                    started_at = now
                    self._ui("hearing", "Hearing you… pause to send")
                elif ev == "end":
                    break
            if started_at is None and now - t_open > cfg.listen_timeout_s:
                self.recorder.stop()
                if cfg.earcon:
                    earcon("close")
                self.ui.log(f"  (no speech for {cfg.listen_timeout_s:.0f}s, mic closed)")
                self.timed_out = True
                return None
            if started_at is not None and now - started_at > cfg.max_utterance_s:
                break
        audio = self.recorder.stop()
        if cfg.earcon:
            earcon("close")
        self._ui("transcribing", "Transcribing…")
        text, dt = self._transcribe(audio)
        if text:
            self.ui.log(f"  {text}   [{dt:.2f}s transcribe]")
        return text

    def _transcribe16(self, audio16: np.ndarray) -> str:
        from voicechat.vad import RATE

        return self.transcriber.transcribe(audio16, RATE)

    def _dictation_loop(self, continue_recording: bool) -> None:
        from voicechat.vad import RATE, SegmentDetector

        cfg = self.cfg
        pad = int(0.2 * RATE)
        seg = SegmentDetector(self.detector.model, pause_ms=cfg.dictation_pause_ms)
        audio = np.zeros(0, dtype=np.float32)  # everything fed so far, at 16 kHz
        committed: list[str] = []
        open_start: int | None = None
        last_activity = time.monotonic()
        last_preview = 0.0
        submit = False
        outcome: str | None = None
        end_state = "idle"
        try:
            if not continue_recording:
                if cfg.earcon:
                    earcon("open")
                self.recorder.start()
            self._ui("dictating", "Dictating… ✓ when done, ✕ to discard")
            self.ui.preview("")
            while outcome is None:
                if self.closing or self.dict_cancel.is_set():
                    outcome = "cancel"
                    break
                if self.dict_finish.is_set():
                    outcome = "finish"
                    break
                new = self.recorder.read_new(0.05)
                now = time.monotonic()
                if new.size:
                    if self.recorder.rate != RATE:
                        import soxr

                        new = soxr.resample(new, self.recorder.rate, RATE)
                    audio = np.concatenate([audio, new])
                    for kind, sample in seg.feed(new):
                        if kind == "start":
                            open_start = sample
                            last_activity = now
                            self._ui("dict_hearing", "Hearing you… pause to commit the sentence")
                        elif kind == "end" and open_start is not None:
                            text = self._transcribe16(audio[max(0, open_start - pad): min(len(audio), sample + pad)])
                            open_start = None
                            last_activity = now
                            self._ui("dictating", "Dictating… ✓ when done, ✕ to discard")
                            if not text:
                                continue
                            if is_cancel(text, cfg.cancel_words):
                                outcome = "cancel"
                                break
                            text, say_send = strip_send_word(text, cfg.send_words)
                            if text:
                                committed.append(text)
                                self.ui.log(f"  + {text}")
                            self.ui.preview(" ".join(committed))
                            if say_send:
                                submit = True
                                outcome = "finish"
                                break
                    if outcome:
                        break
                if (open_start is not None and now - last_preview >= cfg.dictation_preview_s
                        and len(audio) - open_start >= int(0.8 * RATE)):
                    last_preview = now
                    tail = self._transcribe16(audio[max(0, open_start - pad):])
                    self.ui.preview(" ".join(committed), tail)
                if open_start is None and now - last_activity > cfg.dictation_silence_s:
                    outcome = "finish" if committed else "cancel"
                    break
                if len(audio) >= cfg.dictation_max_s * RATE:
                    outcome = "finish"
                    break
            full = self.recorder.stop()
            if cfg.earcon:
                earcon("close")
            if outcome == "finish" and open_start is not None:  # the sentence in progress
                if self.recorder.rate != RATE:
                    import soxr

                    full = soxr.resample(full, self.recorder.rate, RATE)
                text = self._transcribe16(full[max(0, open_start - pad):])
                if text:
                    text, say_send = strip_send_word(text, cfg.send_words)
                    if text:
                        committed.append(text)
                        self.ui.log(f"  + {text}")
                    submit = submit or say_send
            final = " ".join(committed).strip()
            self.last_dictation_text = final if outcome == "finish" else None
            self.ui.preview(None)
            if outcome == "cancel" or not final:
                self.ui.log("  (dictation discarded)" if outcome == "cancel" else "  (dictation: nothing heard)")
                return
            submit = submit or self.auto_submit
            self.ui.log(f"  dictation done: {len(final)} chars" + (" → sending" if submit else " → pasted; press Enter to send"))
            if not self.paste:
                return
            if not self._deliver(final, submit):
                end_state = "your_turn"
                return
            end_state = "idle" if submit else "review"
        except Exception as exc:
            self.ui.log(f"  dictation error: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self._set_state("idle")
            self._ui(end_state, "Sent. Waiting for the reply…" if end_state == "idle" else "")

    def _paste_target(self) -> tuple[str | None, str | None, int | None, bool]:
        """(bundle, name, pid, ours): where a paste would land. When our own app is in front, the
        target is the last other front app, and `ours` says focus must be handed back first."""
        from voicechat.front import front_pid

        pid = front_pid()
        if pid is not None and pid == os.getpid() and self.front is not None and self.front.pid:
            return self.front.bundle, self.front.name, self.front.pid, True
        bundle, name = frontmost_app()
        return bundle, name, pid, False

    def _deliver(self, text: str, submit: bool, anywhere: bool = False) -> bool:
        """Paste `text` (and press Enter when `submit`) into the target app. `anywhere` skips the
        allowed-targets check and remembers the target, for push-to-talk. False means the text
        went to the clipboard instead, and the log says why."""
        from voicechat.front import give_focus_to

        bundle, name, pid, ours = self._paste_target()
        if not anywhere and not target_allowed(bundle, self.cfg.paste_targets, self.last_ptt_target):
            subprocess.run(["pbcopy"], input=text.encode())
            self.ui.log(f"  not pasted: {name or bundle} is in front. Copied to the clipboard instead; "
                        f"hold the key once in your agent window to add it as a target.")
            return False
        if not self._can_paste(text or "send"):
            return False
        if ours and not give_focus_to(pid):
            subprocess.run(["pbcopy"], input=text.encode())
            self.ui.log(f"  not pasted: could not hand focus back to {name or bundle}. Copied to the clipboard instead.")
            return False
        if anywhere:
            self.last_ptt_target = bundle
        paste_text(text, submit, self.cfg.paste_delay_ms if text else 0)
        return True

    def _can_paste(self, text: str) -> bool:
        from voicechat.permissions import accessibility

        if accessibility() is False:
            subprocess.run(["pbcopy"], input=text.encode())
            self.ui.log("  not pasted: Accessibility is not granted for this terminal's app. Copied to the clipboard; "
                        "enable it under Privacy & Security > Accessibility.")
            return False
        return True

    def _transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        t0 = time.monotonic()
        text = self.transcriber.transcribe(audio, self.recorder.rate)
        return text, time.monotonic() - t0


def listen(cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool = False) -> int:
    return Session(cfg, hotkey, auto_submit, paste, hands_free).run()
