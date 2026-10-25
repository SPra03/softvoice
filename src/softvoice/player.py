"""Play float32 mono audio through the default output device as it arrives."""

from __future__ import annotations

import numpy as np


class Playback:
    """One open output stream. `write` blocks until the device has taken the audio, which is
    the backpressure that keeps generation just ahead of playback."""

    def __init__(self, sample_rate: int):
        import sounddevice as sd

        self.sample_rate = sample_rate
        self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", latency="high")
        self.stream.start()
        self.played = 0

    def write(self, chunk: np.ndarray) -> None:
        data = np.ascontiguousarray(chunk, dtype=np.float32).reshape(-1, 1)
        self.stream.write(data)
        self.played += len(data)

    def finish(self) -> None:  # let buffered audio play out
        self.stream.stop()
        self.stream.close()

    def abort(self) -> None:  # drop buffered audio now
        self.stream.abort()
        self.stream.close()


class Player:
    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def open(self) -> Playback:
        return Playback(self.sample_rate)
