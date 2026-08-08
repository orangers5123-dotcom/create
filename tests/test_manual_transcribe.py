import sys
import types

import pytest

from create_text_app import manual_transcribe, whisper_model


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class _FakeWhisperModel:
    def __init__(self, model_size, device=None, compute_type=None):
        self.model_size = model_size
        self.last_call_kwargs = None

    def transcribe(self, wav_path, vad_filter=False, **kwargs):
        self.last_call_kwargs = {"vad_filter": vad_filter, **kwargs}
        return [_FakeSegment("こんにちは"), _FakeSegment(""), _FakeSegment("世界")], object()


@pytest.fixture(autouse=True)
def fake_faster_whisper(monkeypatch):
    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    whisper_model.clear_cache()
    yield
    whisper_model.clear_cache()


def test_transcribe_clip_joins_nonempty_segments():
    text = manual_transcribe.transcribe_clip("clip.wav", "small")
    assert text == "こんにちは 世界"


def test_transcribe_clip_disables_vad_filter():
    model = whisper_model.get_model("small")
    manual_transcribe.transcribe_clip("clip.wav", "small")
    assert model.last_call_kwargs["vad_filter"] is False


def test_transcribe_clip_passes_explicit_language():
    model = whisper_model.get_model("small")
    manual_transcribe.transcribe_clip("clip.wav", "small", language="ja")
    assert model.last_call_kwargs["language"] == "ja"


def test_transcribe_clip_omits_language_when_auto():
    model = whisper_model.get_model("small")
    manual_transcribe.transcribe_clip("clip.wav", "small", language=manual_transcribe.LANGUAGE_AUTO)
    assert "language" not in model.last_call_kwargs
