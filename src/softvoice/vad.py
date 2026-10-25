"""Voice activity detection with Silero VAD on 16 kHz audio."""

from __future__ import annotations

import numpy as np

RATE = 16000
FRAME = 512  # samples per VAD step at 16 kHz (32 ms), fixed by the model


def load_model():
    from silero_vad import load_silero_vad

    return load_silero_vad()


class UtteranceDetector:
    """One utterance: `feed` reports "start" when speech begins and "end" once
    `end_silence_ms` of silence follows it. Used by the quick conversation take."""

    def __init__(self, end_silence_ms: int = 900, threshold: float = 0.5, pad_ms: int = 200, model=None):
        self.model = model if model is not None else load_model()
        self.end_silence_ms = end_silence_ms
        self.threshold = threshold
        self.pad_ms = pad_ms
        self.reset()

    def reset(self) -> None:
        from silero_vad import VADIterator

        self.it = VADIterator(self.model, threshold=self.threshold, sampling_rate=RATE,
                              min_silence_duration_ms=self.end_silence_ms, speech_pad_ms=self.pad_ms)
        self.buf = np.zeros(0, dtype=np.float32)
        self.samples = 0
        self.start_sample: int | None = None
        self.end_sample: int | None = None

    @property
    def started(self) -> bool:
        return self.start_sample is not None

    def feed(self, audio: np.ndarray) -> str | None:
        import torch

        self.buf = np.concatenate([self.buf, np.asarray(audio, dtype=np.float32).reshape(-1)])
        result = None
        while len(self.buf) >= FRAME:
            frame, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            self.samples += FRAME
            ev = self.it(torch.from_numpy(np.ascontiguousarray(frame)))
            if not ev:
                continue
            if "start" in ev and self.start_sample is None:
                self.start_sample = int(ev["start"])
                result = "start"
            if "end" in ev:
                self.end_sample = int(ev["end"])
                return "end"
        return result


class SegmentDetector:
    """Many utterances in a row: `feed` returns ("start", sample) and ("end", sample) events,
    with sample positions counted from `reset`. A pause of `pause_ms` closes a segment.
    Used by dictation, where each closed segment is transcribed and committed."""

    def __init__(self, model, pause_ms: int = 700, threshold: float = 0.5, pad_ms: int = 200):
        self.model = model
        self.pause_ms = pause_ms
        self.threshold = threshold
        self.pad_ms = pad_ms
        self.reset()

    def reset(self) -> None:
        from silero_vad import VADIterator

        self.it = VADIterator(self.model, threshold=self.threshold, sampling_rate=RATE,
                              min_silence_duration_ms=self.pause_ms, speech_pad_ms=self.pad_ms)
        self.buf = np.zeros(0, dtype=np.float32)
        self.samples = 0
        self.open_start: int | None = None

    def feed(self, audio: np.ndarray) -> list[tuple[str, int]]:
        import torch

        self.buf = np.concatenate([self.buf, np.asarray(audio, dtype=np.float32).reshape(-1)])
        events: list[tuple[str, int]] = []
        while len(self.buf) >= FRAME:
            frame, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            self.samples += FRAME
            ev = self.it(torch.from_numpy(np.ascontiguousarray(frame)))
            if not ev:
                continue
            if "start" in ev:
                self.open_start = int(ev["start"])
                events.append(("start", self.open_start))
            if "end" in ev:
                events.append(("end", int(ev["end"])))
                self.open_start = None
        return events
