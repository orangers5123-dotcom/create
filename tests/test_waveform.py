import shutil
import subprocess

import pytest

from create_text_app.waveform import extract_waveform_peaks

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")


@pytest.fixture
def silence_tone_silence_video(tmp_path):
    # 2s silence, 3s tone, 2s silence -- 7s total.
    audio = tmp_path / "audio.wav"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[aout]",
            "-map", "[aout]", "-ar", "16000", "-ac", "1",
            str(audio),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    video = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=7",
            "-i", str(audio),
            "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return str(video)


def test_extract_waveform_peaks_returns_requested_length(silence_tone_silence_video, tmp_path):
    peaks = extract_waveform_peaks(silence_tone_silence_video, 7.0, num_points=100, temp_dir=str(tmp_path))
    assert len(peaks) == 100
    assert all(0.0 <= p <= 1.0 for p in peaks)


def test_extract_waveform_peaks_distinguishes_silence_from_tone(silence_tone_silence_video, tmp_path):
    peaks = extract_waveform_peaks(silence_tone_silence_video, 7.0, num_points=700, temp_dir=str(tmp_path))
    # ~100 points per second at 700 points / 7s. Silence is the first ~2s and
    # last ~2s; tone is the middle ~3s.
    silence_region = peaks[:150]
    tone_region = peaks[250:550]

    avg_silence = sum(silence_region) / len(silence_region)
    avg_tone = sum(tone_region) / len(tone_region)

    assert avg_tone > avg_silence * 5


def test_extract_waveform_peaks_handles_zero_duration():
    assert extract_waveform_peaks("/nonexistent.mp4", 0.0, num_points=100) == []


def test_extract_waveform_peaks_handles_zero_num_points(silence_tone_silence_video, tmp_path):
    assert extract_waveform_peaks(silence_tone_silence_video, 7.0, num_points=0, temp_dir=str(tmp_path)) == []
