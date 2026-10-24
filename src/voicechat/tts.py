"""Pocket TTS wrapper: one loaded model, one voice, streaming synthesis."""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

import numpy as np

from voicechat.config import Config

log = logging.getLogger("voicechat.tts")

PREDEFINED_VOICES = [
    "alba", "anna", "azelma", "bill_boerst", "caro_davy", "charles", "cosette", "eponine", "eve",
    "fantine", "george", "jane", "javert", "jean", "marius", "mary", "michael", "paul",
    "peter_yearsley", "stuart_bell", "vera",
    "giovanni", "lola", "juergen", "rafael", "daan", "estelle",
]


class Speaker:
    def __init__(self, cfg: Config):
        import torch
        from pocket_tts import TTSModel

        torch.set_num_threads(max(2, min(4, torch.get_num_threads())))
        t0 = time.monotonic()
        self.model = TTSModel.load_model(language=cfg.language)
        self.sample_rate: int = self.model.sample_rate
        self.state = self.model.get_state_for_audio_prompt(cfg.voice)
        self.voice = cfg.voice
        log.info("Pocket TTS ready: language=%s voice=%s sample_rate=%d load=%.1fs",
                 cfg.language, cfg.voice, self.sample_rate, time.monotonic() - t0)

    def set_voice(self, voice: str) -> None:
        self.state = self.model.get_state_for_audio_prompt(voice)
        self.voice = voice

    def stream(self, text: str, stop: threading.Event) -> Iterator[np.ndarray]:
        """Yield float32 mono chunks at `sample_rate` as they are generated."""
        for chunk in self.model.generate_audio_stream(self.state, text, stop=stop):
            yield chunk.detach().cpu().numpy().astype(np.float32).reshape(-1)

    def synthesize(self, text: str) -> np.ndarray:
        """Whole utterance as one array (used by tests and `voicechat say --out`)."""
        parts = list(self.stream(text, threading.Event()))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
