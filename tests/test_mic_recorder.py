import sys
import types

import numpy as np
import pytest

from create_text_app.mic_recorder import MicRecorder, MicRecorderError


class _FakeInputStream:
    """Stands in for sounddevice.InputStream: capturing the callback so the
    test can push fake audio chunks through it, like real audio hardware
    would.
    """

    last_instance = None

    def __init__(self, samplerate, channels, dtype, callback):
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.callback = callback
        self.started = False
        self.closed = False
        _FakeInputStream.last_instance = self

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def push_audio(self, frames: int):
        chunk = np.zeros((frames, self.channels), dtype=np.int16)
        self.callback(chunk, frames, None, None)


@pytest.fixture(autouse=True)
def fake_sounddevice(monkeypatch):
    fake_module = types.ModuleType("sounddevice")
    fake_module.InputStream = _FakeInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)
    yield


def test_start_then_stop_writes_wav(tmp_path):
    rec = MicRecorder(samplerate=16000, channels=1)
    rec.start()
    assert rec.is_recording

    stream = _FakeInputStream.last_instance
    assert stream.started
    stream.push_audio(1600)
    stream.push_audio(1600)

    out_path = str(tmp_path / "clip.wav")
    result = rec.stop(out_path)

    assert result == out_path
    assert not rec.is_recording
    assert stream.closed

    from scipy.io import wavfile
    rate, data = wavfile.read(out_path)
    assert rate == 16000
    assert len(data) == 3200


def test_stop_without_start_returns_none(tmp_path):
    rec = MicRecorder()
    assert rec.stop(str(tmp_path / "clip.wav")) is None


def test_stop_with_no_captured_audio_returns_none(tmp_path):
    rec = MicRecorder()
    rec.start()
    result = rec.stop(str(tmp_path / "clip.wav"))
    assert result is None


def test_start_is_a_noop_if_already_recording():
    rec = MicRecorder()
    rec.start()
    first_stream = _FakeInputStream.last_instance
    rec.start()
    assert _FakeInputStream.last_instance is first_stream


def test_cancel_discards_audio(tmp_path):
    rec = MicRecorder()
    rec.start()
    _FakeInputStream.last_instance.push_audio(1600)
    rec.cancel()
    assert not rec.is_recording
    assert rec.stop(str(tmp_path / "clip.wav")) is None


def test_missing_sounddevice_raises_friendly_error(monkeypatch):
    # A None entry in sys.modules makes `import sounddevice` raise
    # ImportError, simulating the package not being installed.
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    rec = MicRecorder()
    with pytest.raises(MicRecorderError):
        rec.start()
