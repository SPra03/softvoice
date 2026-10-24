"""Listening: push-to-talk, and hands-free turn-taking driven by the speaker daemon's events.

Push-to-talk: hold a key, speak, release; the transcript is pasted where your cursor is.
Hands-free: when the daemon finishes speaking an agent's reply, the mic opens (beep), Silero VAD
waits for you to stop talking, Parakeet transcribes, and the text is pasted and sent, but only if
the frontmost app is a terminal or agent app, or the app you last used push-to-talk in.
Pressing the key at any time interrupts speech and takes over from hands-free listening.
"""

from __future__ import annotations

import fnmatch
import queue
import subprocess
import sys
import threading
import time
import traceback

import numpy as np

from voicechat.config import Config

RECORD_RATE = 16000


# -- small helpers ------------------------------------------------------------------

def resolve_key(name: str):
    from pynput import keyboard

    name = name.strip().lower()
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    raise SystemExit(f"unknown hotkey {name!r}; use a pynput key name such as alt_r, cmd_r, ctrl_r, f5")


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
    from pynput import keyboard

    old = subprocess.run(["pbpaste"], capture_output=True).stdout
    subprocess.run(["pbcopy"], input=text.encode())
    time.sleep(delay_ms / 1000)
    kb = keyboard.Controller()
    with kb.pressed(keyboard.Key.cmd):
        kb.press("v")
        kb.release("v")
    if submit:
        time.sleep(0.15)
        kb.press(keyboard.Key.enter)
        kb.release(keyboard.Key.enter)
    time.sleep(0.3)
    subprocess.run(["pbcopy"], input=old)  # give the clipboard back


def _interrupt_speech(reason: str = "ptt") -> None:
    try:
        from voicechat.client import send

        send({"cmd": "stop", "reason": reason}, autostart=False, timeout=0.3)
    except Exception:
        pass


# -- microphone ---------------------------------------------------------------------

class Recorder:
    """Keeps the microphone open; buffers audio only while recording.
    `read_new` hands out fresh audio for live VAD, `stop` returns the whole take."""

    def __init__(self, rate: int = RECORD_RATE):
        import sounddevice as sd

        self.lock = threading.Lock()
        self.recording = False
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


# -- the session --------------------------------------------------------------------

class Session:
    def __init__(self, cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool):
        self.cfg = cfg
        self.hotkey = hotkey
        self.auto_submit = auto_submit
        self.paste = paste
        self.hands_free = hands_free
        self.state = "idle"  # idle | ptt | auto
        self.state_lock = threading.Lock()
        self.closing = False
        self.auto_cancel = threading.Event()
        self.auto_done = threading.Event()
        self.auto_done.set()
        self.resume_after = False
        self.last_ptt_target: str | None = None
        self.ptt_t0 = 0.0
        self.transcriber = None
        self.recorder: Recorder | None = None
        self.detector = None

    # -- lifecycle --

    def run(self) -> int:
        from pynput import keyboard

        from voicechat.stt import Transcriber

        key = resolve_key(self.hotkey)
        print(f"loading {self.cfg.stt_model} ...", flush=True)
        self.transcriber = Transcriber(self.cfg.stt_model)
        if self.hands_free:
            from voicechat.client import ensure_daemon
            from voicechat.vad import UtteranceDetector

            self.detector = UtteranceDetector(self.cfg.end_silence_ms)
            print("starting the speaker daemon ...", flush=True)
            if not ensure_daemon():
                print("the speaker daemon did not start; see `voicechat log`", file=sys.stderr)
                return 1
        self.recorder = Recorder()
        print(f"ready. Hold {self.hotkey} and speak; release to {'paste' if self.paste else 'print'}. Ctrl+C to quit.", flush=True)
        if self.hands_free:
            print(f"hands-free: after each spoken reply the mic opens (beep). Pause {self.cfg.end_silence_ms / 1000:.1f}s "
                  f"to send; say \"{self.cfg.cancel_words[0]}\" to discard; silence for {self.cfg.listen_timeout_s:.0f}s closes the mic.", flush=True)
        from voicechat.permissions import check_and_request, input_monitoring

        check_and_request(need_paste=self.paste, need_hotkey=True, out=lambda m: print(m, flush=True))
        print("Microphone: if nothing is ever heard, enable this terminal's app under Privacy & Security > Microphone.", flush=True)

        self.listener = None
        if input_monitoring() in ("granted", "unavailable"):
            self._start_key_listener(key)
        else:  # start the key watcher the moment the permission is toggled on; hands-free works meanwhile
            threading.Thread(target=self._wait_for_input_monitoring, args=(key,), daemon=True).start()
        if self.hands_free:
            threading.Thread(target=self._event_loop, name="events", daemon=True).start()
        try:
            while not self.closing:
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nbye", file=sys.stderr)
        finally:
            self.closing = True
            self.auto_cancel.set()
            if self.listener:
                self.listener.stop()
            self.recorder.close()
        return 0

    def _start_key_listener(self, key) -> None:
        from pynput import keyboard

        self.listener = keyboard.Listener(on_press=lambda k: self._on_press(k, key), on_release=lambda k: self._on_release(k, key))
        self.listener.start()

    def _wait_for_input_monitoring(self, key) -> None:
        from voicechat.permissions import input_monitoring

        while not self.closing:
            time.sleep(2.0)
            if input_monitoring() == "granted":
                self._start_key_listener(key)
                print(f"Input Monitoring granted: hold {self.hotkey} to talk.", flush=True)
                return

    def _set_state(self, new: str, expect: str | None = None) -> bool:
        with self.state_lock:
            if expect is not None and self.state != expect:
                return False
            self.state = new
            return True

    # -- push-to-talk --

    def _on_press(self, k, key) -> None:
        if k != key:
            return
        with self.state_lock:
            if self.state == "ptt":
                return  # key repeat
            was_auto = self.state == "auto"
        threading.Thread(target=_interrupt_speech, daemon=True).start()
        if was_auto:
            self.auto_cancel.set()
            self.auto_done.wait(1.0)
        if not self._set_state("ptt", expect="idle"):
            return
        self.ptt_t0 = time.monotonic()
        self.recorder.start()
        print("● listening ...", flush=True)

    def _on_release(self, k, key) -> None:
        if k != key:
            return
        with self.state_lock:
            if self.state != "ptt":
                return
        threading.Thread(target=self._finish_ptt, daemon=True).start()

    def _finish_ptt(self) -> None:
        try:
            audio = self.recorder.stop()
            held = time.monotonic() - self.ptt_t0
            bundle, name = frontmost_app()
            text, dt = self._transcribe(audio)
            if not text:
                print(f"  (heard nothing, {held:.1f}s)", flush=True)
                return
            print(f"  {text}   [{held:.1f}s speech, {dt:.2f}s transcribe]", flush=True)
            if self.paste and self._can_paste(text):
                self.last_ptt_target = bundle
                paste_text(text, self.auto_submit, self.cfg.paste_delay_ms)
        except Exception as exc:
            print(f"  push-to-talk error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
        finally:
            self._set_state("idle")

    # -- hands-free --

    def _event_loop(self) -> None:
        from voicechat.client import ensure_daemon, subscribe

        while not self.closing:
            try:
                ensure_daemon()
                for ev in subscribe():
                    if self.closing:
                        return
                    self._on_event(ev)
            except Exception:
                pass
            time.sleep(2.0)  # daemon gone; come back when it is

    def _on_event(self, ev: dict) -> None:
        kind = ev.get("event")
        if kind == "speech_start":
            with self.state_lock:
                in_auto = self.state == "auto"
            if in_auto:  # don't record the speaker; pick the turn up again afterwards
                self.resume_after = True
                self.auto_cancel.set()
        elif kind == "speech_end":
            if ev.get("interrupted"):
                self.resume_after = False  # you typed, or you're already talking
                return
            if ev.get("source") == "Stop" or self.resume_after:
                self.resume_after = False
                self._start_auto()

    def _start_auto(self) -> None:
        if not self._set_state("auto", expect="idle"):
            return
        self.auto_cancel.clear()
        self.auto_done.clear()
        threading.Thread(target=self._auto_listen, name="auto-listen", daemon=True).start()

    def _auto_listen(self) -> None:
        cfg = self.cfg
        try:
            if cfg.earcon:
                earcon("open")
            self.detector.reset()
            self.recorder.start()
            t_open = time.monotonic()
            started_at: float | None = None
            print("🎤 your turn ...", flush=True)
            while True:
                if self.auto_cancel.is_set() or self.closing:
                    self.recorder.stop()
                    print("  (hands-free cancelled)", flush=True)
                    return
                new = self.recorder.read_new(0.05)
                now = time.monotonic()
                if new.size:
                    if self.recorder.rate != RECORD_RATE:
                        import soxr

                        new = soxr.resample(new, self.recorder.rate, RECORD_RATE)
                    ev = self.detector.feed(new)
                    if ev == "start":
                        started_at = now
                        print("  ● hearing you ...", flush=True)
                    elif ev == "end":
                        break
                if started_at is None and now - t_open > cfg.listen_timeout_s:
                    self.recorder.stop()
                    if cfg.earcon:
                        earcon("close")
                    print(f"  (no speech for {cfg.listen_timeout_s:.0f}s, mic closed; hold {self.hotkey} to talk)", flush=True)
                    return
                if started_at is not None and now - started_at > cfg.max_utterance_s:
                    break
            audio = self.recorder.stop()
            if cfg.earcon:
                earcon("close")
            bundle, name = frontmost_app()
            text, dt = self._transcribe(audio)
            if not text:
                print("  (heard nothing)", flush=True)
                return
            if is_cancel(text, cfg.cancel_words):
                print(f"  \"{text}\" — discarded", flush=True)
                return
            print(f"  {text}   [{dt:.2f}s transcribe]", flush=True)
            if not self.paste:
                return
            if not target_allowed(bundle, cfg.paste_targets, self.last_ptt_target):
                subprocess.run(["pbcopy"], input=text.encode())
                print(f"  not pasted: {name or bundle} is in front. Copied to the clipboard instead; "
                      f"use the key once in your agent window to add it as a target.", flush=True)
                return
            if not self._can_paste(text):
                return
            paste_text(text, submit=True, delay_ms=cfg.paste_delay_ms)
            print("  → sent", flush=True)
        except Exception as exc:
            print(f"  hands-free error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
        finally:
            self._set_state("idle")
            self.auto_done.set()

    def _can_paste(self, text: str) -> bool:
        from voicechat.permissions import accessibility

        if accessibility() is False:
            subprocess.run(["pbcopy"], input=text.encode())
            print("  not pasted: Accessibility is not granted for this terminal's app. Copied to the clipboard; "
                  "enable it under Privacy & Security > Accessibility.", flush=True)
            return False
        return True

    def _transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        t0 = time.monotonic()
        text = self.transcriber.transcribe(audio, self.recorder.rate)
        return text, time.monotonic() - t0


def listen(cfg: Config, hotkey: str, auto_submit: bool, paste: bool, hands_free: bool = False) -> int:
    return Session(cfg, hotkey, auto_submit, paste, hands_free).run()
