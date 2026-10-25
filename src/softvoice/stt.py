"""Parakeet speech-to-text on Apple Silicon through MLX, fed raw audio (no ffmpeg).

All MLX work happens on one dedicated thread. MLX streams belong to the thread that created
them, so calling the model from another thread fails with
"There is no Stream(cpu, 1) in current thread". Callers just use `transcribe()`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("softvoice.stt")


class Transcriber:
    def __init__(self, model_id: str, warm_up: bool = True):
        self.model_id = model_id
        self.sample_rate: int = 16000
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._serve, args=(warm_up,), name="parakeet", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._error:
            raise self._error

    # -- the model thread --

    def _serve(self, warm_up: bool) -> None:
        try:
            from parakeet_mlx import from_pretrained

            t0 = time.monotonic()
            self.model = from_pretrained(self.model_id)
            self.sample_rate = self.model.preprocessor_config.sample_rate
            load = time.monotonic() - t0
            if warm_up:  # first MLX call compiles kernels; do it now, not on the first keypress
                self._transcribe(np.zeros(self.sample_rate, dtype=np.float32), self.sample_rate)
            log.info("Parakeet ready: %s, %d Hz, load %.1fs, warm-up %.1fs", self.model_id, self.sample_rate, load,
                     time.monotonic() - t0 - load)
        except Exception as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            audio, sample_rate, job = self._jobs.get()
            try:
                job["result"] = self._transcribe(audio, sample_rate)
            except Exception as exc:
                job["error"] = exc
            job["done"].set()

    def _transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate != self.sample_rate:
            import soxr

            audio = soxr.resample(audio, sample_rate, self.sample_rate)
        if len(audio) < self.sample_rate // 4:  # under 250 ms: nothing to hear
            return ""
        # float32 only: the library's own loader returns float32, and bfloat16 breaks its complex view
        mel = get_logmel(mx.array(audio), self.model.preprocessor_config)
        result = self.model.generate(mel)[0]
        return result.text.strip()

    # -- callers, from any thread --

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        job: dict = {"done": threading.Event()}
        self._jobs.put((audio, sample_rate, job))
        job["done"].wait()
        if "error" in job:
            raise job["error"]
        return job["result"]

    def transcribe_file(self, path: Path) -> str:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return self.transcribe(audio.mean(axis=1), sr)
