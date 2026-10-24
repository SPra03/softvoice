"""Parakeet speech-to-text on Apple Silicon through MLX, fed raw audio (no ffmpeg)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("voicechat.stt")


class Transcriber:
    def __init__(self, model_id: str, warm_up: bool = True):
        from parakeet_mlx import from_pretrained

        t0 = time.monotonic()
        self.model = from_pretrained(model_id)
        self.sample_rate: int = self.model.preprocessor_config.sample_rate
        load = time.monotonic() - t0
        if warm_up:  # first MLX call compiles kernels; do it now, not on the first keypress
            self.transcribe(np.zeros(self.sample_rate, dtype=np.float32), self.sample_rate)
        log.info("Parakeet ready: %s, %d Hz, load %.1fs, warm-up %.1fs", model_id, self.sample_rate, load,
                 time.monotonic() - t0 - load)

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
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

    def transcribe_file(self, path: Path) -> str:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return self.transcribe(audio.mean(axis=1), sr)
