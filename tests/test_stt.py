"""The transcriber without a model: a fake parakeet_mlx stands in, MLX itself is real."""

import sys
import threading
import types

import numpy as np


def fake_parakeet(monkeypatch, generate):
    audio = types.ModuleType("parakeet_mlx.audio")
    audio.get_logmel = lambda wave, cfg: wave
    pkg = types.ModuleType("parakeet_mlx")
    pkg.audio = audio
    model = types.SimpleNamespace(preprocessor_config=types.SimpleNamespace(sample_rate=16000), generate=generate)
    pkg.from_pretrained = lambda model_id: model
    monkeypatch.setitem(sys.modules, "parakeet_mlx", pkg)
    monkeypatch.setitem(sys.modules, "parakeet_mlx.audio", audio)


def test_mlx_cache_is_handed_back_after_every_call(monkeypatch):
    import mlx.core as mx
    from softvoice.stt import Transcriber

    cleared: list[tuple[str, int]] = []  # (thread, bytes waiting in the cache) at each clear
    real_clear = mx.clear_cache

    def clear_cache():
        cleared.append((threading.current_thread().name, mx.get_cache_memory()))
        real_clear()

    monkeypatch.setattr(mx, "clear_cache", clear_cache)

    def generate(mel):
        scratch = mx.zeros((1024, 1024))  # 4 MB freed once the GPU retires it, like a real take's activations
        mx.eval(scratch)
        del scratch
        return [types.SimpleNamespace(text=" hello ")]

    fake_parakeet(monkeypatch, generate)
    t = Transcriber("fake/parakeet")  # the warm-up is one call
    assert t.transcribe(np.zeros(16000, dtype=np.float32), 16000) == "hello"
    assert t.transcribe(np.zeros(32000, dtype=np.float32), 16000) == "hello"
    assert [thread for thread, _ in cleared] == ["parakeet"] * 3  # on the model thread, before the caller is released
    assert all(waiting >= 4 * 2**20 for _, waiting in cleared)  # each clear found that take's buffers
    assert mx.get_cache_memory() == 0
