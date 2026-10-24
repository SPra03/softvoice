"""The long-running speaker process.

Hooks and the CLI talk to it over a Unix socket with one JSON object per line and get
one JSON object back. It keeps the Pocket TTS model warm and plays replies in order.
"""

from __future__ import annotations

import collections
import fcntl
import json
import logging
import logging.handlers
import os
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from voicechat import __version__
from voicechat.clean import clean
from voicechat.config import LOG_PATH, PID_PATH, SOCKET_PATH, Config, ensure_home

log = logging.getLogger("voicechat.daemon")


@dataclass
class Utterance:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    raw: bool = False
    enqueued_at: float = field(default_factory=time.monotonic)


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.queue: collections.deque[Utterance] = collections.deque()
        self.cv = threading.Condition()
        self.current_stop = threading.Event()
        self.speaking: str | None = None
        self.muted = False
        self.ready = threading.Event()
        self.closing = False
        self.speaker = None
        self.player = None
        self._recent: collections.deque[tuple[str, float]] = collections.deque(maxlen=8)
        self.subscribers: list = []
        self.sub_lock = threading.Lock()
        self.stop_reason: str | None = None
        self.last_spoken: Utterance | None = None
        self.worker = threading.Thread(target=self._run, name="speaker", daemon=True)
        self.worker.start()

    # -- commands -------------------------------------------------------------------

    def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = req.get("cmd")
        if cmd == "speak":
            return self.enqueue(str(req.get("text", "")), req.get("meta") or {}, bool(req.get("raw")))
        if cmd == "stop":
            self.stop_all(str(req.get("reason") or "cli"))
            return {"ok": True}
        if cmd == "mute":
            self.muted = True
            self.stop_all("mute")
            return {"ok": True, "muted": True}
        if cmd == "unmute":
            self.muted = False
            return {"ok": True, "muted": False}
        if cmd == "status":
            return self.status()
        if cmd == "voice":
            return self.set_voice(str(req.get("voice", "")))
        if cmd == "replay":
            if not self.last_spoken:
                return {"ok": True, "skipped": "nothing to replay"}
            self.stop_all("replay")
            return self.enqueue(self.last_spoken.text, {"event": "replay", "session_id": "replay",
                                                        "project": self.last_spoken.meta.get("project")}, raw=True)
        if cmd == "quit":
            self.closing = True
            self.broadcast({"event": "daemon_quit"})
            self.stop_all("quit")
            with self.cv:
                self.cv.notify_all()
            return {"ok": True}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    def enqueue(self, text: str, meta: dict[str, Any], raw: bool) -> dict[str, Any]:
        if self.muted:
            self._silent_turn(meta)
            return {"ok": True, "skipped": "muted"}
        if not raw:
            cleaned = clean(text, self.cfg.max_chars, self.cfg.truncation_suffix)
            spoken = cleaned.text
            if spoken and self.cfg.announce_project and meta.get("project") and not meta.get("priority"):
                spoken = f"{meta['project']}: {spoken}"
        else:
            spoken = text.strip()
        if not spoken:
            self._silent_turn(meta)
            return {"ok": True, "skipped": "nothing to say"}
        now = time.monotonic()
        key = f"{meta.get('session_id')}|{spoken}"
        if any(k == key and now - t < 5 for k, t in self._recent):
            return {"ok": True, "skipped": "duplicate"}
        self._recent.append((key, now))
        utt = Utterance(spoken, meta, raw)
        with self.cv:
            if meta.get("priority"):
                self.queue.appendleft(utt)
            else:
                self.queue.append(utt)
            self.cv.notify()
        log.info("queued %d chars from %s (%s)", len(spoken), meta.get("project") or "?", meta.get("event") or "say")
        return {"ok": True, "queued": len(self.queue), "chars": len(spoken)}

    def stop_all(self, reason: str = "cli") -> None:
        with self.cv:
            self.queue.clear()
        self.stop_reason = reason
        self.current_stop.set()

    # -- events for listeners (hands-free mode) ------------------------------------

    def add_subscriber(self, wfile) -> None:
        with self.sub_lock:
            self.subscribers.append(wfile)

    def remove_subscriber(self, wfile) -> None:
        with self.sub_lock:
            if wfile in self.subscribers:
                self.subscribers.remove(wfile)

    def broadcast(self, event: dict[str, Any]) -> None:
        line = (json.dumps(event) + "\n").encode()
        with self.sub_lock:
            dead = []
            for wfile in self.subscribers:
                try:
                    wfile.write(line)
                    wfile.flush()
                except OSError:
                    dead.append(wfile)
            for wfile in dead:
                self.subscribers.remove(wfile)

    def _event(self, name: str, meta: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {"event": name, "source": meta.get("event"), "project": meta.get("project"),
                "session_id": meta.get("session_id"), **extra}

    def _silent_turn(self, meta: dict[str, Any]) -> None:
        """A reply that produced no speech still ends the agent's turn: tell listeners."""
        if meta.get("event") == "Stop":
            self.broadcast(self._event("speech_end", meta, spoken=False, interrupted=False, reason=None, seconds=0.0))

    def set_voice(self, voice: str) -> dict[str, Any]:
        if not voice:
            return {"ok": False, "error": "no voice given"}
        if not self.ready.wait(timeout=120) or self.speaker is None:
            return {"ok": False, "error": "model not ready"}
        try:
            self.speaker.set_voice(voice)
        except Exception as exc:  # bad name, bad file
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "voice": voice}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "pid": os.getpid(),
            "ready": self.ready.is_set(),
            "speaking": self.speaking,
            "queued": len(self.queue),
            "muted": self.muted,
            "voice": self.speaker.voice if self.speaker else self.cfg.voice,
            "language": self.cfg.language,
        }

    # -- worker --------------------------------------------------------------------

    def _run(self) -> None:
        from voicechat.player import Player
        from voicechat.tts import Speaker

        try:
            self.speaker = Speaker(self.cfg)
            self.player = Player(self.speaker.sample_rate)
        except Exception:
            log.exception("could not load the TTS model; exiting")
            os._exit(3)
        self.ready.set()
        while not self.closing:
            with self.cv:
                while not self.queue and not self.closing:
                    self.cv.wait()
                if self.closing:
                    break
                utt = self.queue.popleft()
            self._speak(utt)

    def _speak(self, utt: Utterance) -> None:
        self.current_stop = threading.Event()
        self.stop_reason = None
        self.speaking = utt.text[:80]
        if utt.meta.get("event") != "replay":
            self.last_spoken = utt
        t0 = time.monotonic()
        first = [None]
        self.broadcast(self._event("speech_start", utt.meta, chars=len(utt.text)))
        played = 0

        def timed():
            for chunk in self.speaker.stream(utt.text, self.current_stop):
                if first[0] is None:
                    first[0] = time.monotonic() - t0
                yield chunk

        try:
            played = self.player.play(timed(), self.current_stop)
            log.info("spoke %d chars, first audio %.2fs, %.1fs audio%s", len(utt.text),
                     first[0] or -1, played / self.speaker.sample_rate,
                     f" (interrupted: {self.stop_reason})" if self.current_stop.is_set() else "")
        except Exception:
            log.exception("playback failed")
        finally:
            self.speaking = None
            self.broadcast(self._event("speech_end", utt.meta, spoken=True, interrupted=self.current_stop.is_set(),
                                       reason=self.stop_reason, seconds=round(played / self.speaker.sample_rate, 2)))


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(1_000_000)
        if not line:
            return
        engine: Engine = self.server.engine  # type: ignore[attr-defined]
        try:
            req = json.loads(line)
            if req.get("cmd") == "subscribe":
                self._subscribe(engine)
                return
            resp = engine.handle(req)
        except Exception as exc:
            log.exception("bad request")
            resp = {"ok": False, "error": str(exc)}
        self.wfile.write((json.dumps(resp) + "\n").encode())

    def _subscribe(self, engine: Engine) -> None:
        """Keep the connection open and push events until the client hangs up."""
        self.wfile.write((json.dumps({"ok": True, "subscribed": True, "status": engine.status()}) + "\n").encode())
        self.wfile.flush()
        engine.add_subscriber(self.wfile)
        try:
            while self.rfile.readline():  # clients may send keepalives; EOF means they left
                pass
        finally:
            engine.remove_subscriber(self.wfile)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: str, engine: Engine):
        self.engine = engine
        super().__init__(path, Handler)


def socket_alive(path=SOCKET_PATH, timeout: float = 0.5) -> bool:
    if not path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _setup_logging(to_stderr: bool) -> None:
    ensure_home()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=2)
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if to_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    for noisy in ("httpx", "httpx2", "urllib3", "huggingface_hub", "filelock", "pocket_tts"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def serve(foreground: bool = False) -> int:
    _setup_logging(to_stderr=foreground)
    ensure_home()
    lock_fd = os.open(PID_PATH, os.O_RDWR | os.O_CREAT, 0o644)
    # A daemon that just quit can hold the lock for a moment while the interpreter tears
    # down, and two hooks can race to start us. Retry briefly instead of giving up.
    deadline = time.monotonic() + 15
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if socket_alive():
                log.info("another daemon is already answering; exiting")
                return 0
            if time.monotonic() > deadline:
                log.info("another daemon holds the lock; exiting")
                return 0
            time.sleep(0.2)
    os.ftruncate(lock_fd, 0)
    os.write(lock_fd, str(os.getpid()).encode())
    if socket_alive():
        log.info("socket already answering; exiting")
        return 0
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    cfg = Config.load()
    engine = Engine(cfg)
    server = Server(str(SOCKET_PATH), engine)
    os.chmod(SOCKET_PATH, 0o600)
    log.info("voicechat %s listening on %s (pid %d)", __version__, SOCKET_PATH, os.getpid())
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    try:
        while not engine.closing:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        log.info("daemon stopped")
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    return 0
