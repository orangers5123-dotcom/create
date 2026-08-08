import sys
import types

import pytest

from create_text_app import whisper_model


class _FakeWhisperModel:
    instances_created = 0

    def __init__(self, model_size, device=None, compute_type=None):
        self.model_size = model_size
        _FakeWhisperModel.instances_created += 1


@pytest.fixture(autouse=True)
def fake_faster_whisper(monkeypatch):
    _FakeWhisperModel.instances_created = 0
    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    whisper_model.clear_cache()
    yield
    whisper_model.clear_cache()


def test_get_model_loads_once_per_size():
    m1 = whisper_model.get_model("small")
    m2 = whisper_model.get_model("small")
    assert m1 is m2
    assert _FakeWhisperModel.instances_created == 1


def test_get_model_loads_separately_per_size():
    whisper_model.get_model("small")
    whisper_model.get_model("large-v3")
    assert _FakeWhisperModel.instances_created == 2


def test_clear_cache_forces_reload():
    whisper_model.get_model("small")
    whisper_model.clear_cache()
    whisper_model.get_model("small")
    assert _FakeWhisperModel.instances_created == 2
