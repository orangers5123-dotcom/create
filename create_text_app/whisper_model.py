"""Shared, cached faster-whisper model loading.

Loading a WhisperModel takes real time (seconds, more for larger sizes).
The auto-transcribe flow only loads once per run, but manual dictation
mode transcribes many short per-segment clips back to back -- reloading
the model for every clip would make each recording take as long as the
first. Cache one loaded model per size and reuse it.
"""

import threading
from typing import Dict

_lock = threading.Lock()
_models: Dict[str, "object"] = {}


def get_model(model_size: str):
    """Return a cached ``WhisperModel`` for ``model_size``, loading it on
    first use. Thread-safe -- callers may run on a background worker thread.
    """

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            "文字起こしには 'faster-whisper' パッケージが必要です。"
            " pip install faster-whisper でインストールしてください。"
        ) from exc

    with _lock:
        model = _models.get(model_size)
        if model is None:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            _models[model_size] = model
        return model


def clear_cache() -> None:
    """Drop all cached models (mainly for tests)."""

    with _lock:
        _models.clear()
