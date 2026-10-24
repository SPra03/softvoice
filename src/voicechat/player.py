"""Play float32 mono audio chunks through the default output device as they arrive."""

from __future__ import annotations

import threading
from typing import Iterable

import numpy as np


class Player:
    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def play(self, chunks: Iterable[np.ndarray], stop: threading.Event) -> int:
        """Play chunks until exhausted or `stop` is set. Returns samples played."""
        import sounddevice as sd

        played = 0
        stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, dtype="float32", latency="high")
        stream.start()
        try:
            for chunk in chunks:
                if stop.is_set():
                    break
                data = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1, 1)
                stream.write(data)  # blocks until the device has taken it: natural backpressure
                played += len(data)
            if stop.is_set():
                stream.abort()
            else:
                stream.stop()  # waits for buffered audio to finish
        finally:
            stream.close()
        return played
