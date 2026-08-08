import sys
import types

import numpy as np
import pytest
from scipy.io import wavfile

from create_text_app.audio_playback import AudioPlaybackError, play_wav, stop


class _FakeSoundDevice:
    def __init__(self):
        self.play_calls = []
        self.stop_calls = 0
        self.raise_on_play = None

    def play(self, data, samplerate):
        if self.raise_on_play:
            raise self.raise_on_play
        self.play_calls.append((data, samplerate))

    def stop(self):
        self.stop_calls += 1


@pytest.fixture
def fake_sd(monkeypatch):
    fake = _FakeSoundDevice()
    fake_module = types.ModuleType("sounddevice")
    fake_module.play = fake.play
    fake_module.stop = fake.stop
    monkeypatch.setitem(sys.modules, "sounddevice", fake_module)
    return fake


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "clip.wav"
    data = np.zeros(1600, dtype=np.int16)
    wavfile.write(str(path), 16000, data)
    return str(path)


def test_play_wav_reads_and_plays(fake_sd, wav_file):
    play_wav(wav_file)
    assert len(fake_sd.play_calls) == 1
    data, samplerate = fake_sd.play_calls[0]
    assert samplerate == 16000
    assert len(data) == 1600


def test_play_wav_missing_sounddevice_raises_friendly_error(monkeypatch, wav_file):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(AudioPlaybackError):
        play_wav(wav_file)


def test_play_wav_bad_file_raises_friendly_error(fake_sd, tmp_path):
    bad_path = str(tmp_path / "not_a_wav.wav")
    with open(bad_path, "w") as f:
        f.write("not audio data")
    with pytest.raises(AudioPlaybackError):
        play_wav(bad_path)


def test_play_wav_device_error_raises_friendly_error(fake_sd, wav_file):
    fake_sd.raise_on_play = RuntimeError("no output device")
    with pytest.raises(AudioPlaybackError):
        play_wav(wav_file)


def test_stop_calls_sounddevice_stop(fake_sd):
    stop()
    assert fake_sd.stop_calls == 1


def test_stop_is_a_noop_without_sounddevice(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    stop()  # should not raise
