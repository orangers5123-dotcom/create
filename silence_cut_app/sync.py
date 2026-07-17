"""Two-camera audio sync: find the time offset between two takes of the same
moment by cross-correlating their audio, so cuts computed from one camera's
silence can be mapped onto the other camera's source timecodes.
"""

import wave
from typing import Optional, Tuple

import numpy as np
from scipy.signal import correlate

from davinci_auto_cut.audio_extract import extract_audio_segment
from davinci_auto_cut.ffprobe import probe_duration


def read_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"expected a mono wav file, got {wf.getnchannels()} channels: {path}")
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    return samples, sample_rate


def find_offset_seconds(
    cam1_samples: np.ndarray,
    cam2_samples: np.ndarray,
    sample_rate: int,
    max_offset_sec: Optional[float] = None,
) -> float:
    """Find the offset between two audio signals of the same real-world
    event, via cross-correlation.

    Returns ``offset_sec`` such that, for the same moment,
    ``cam2_time = cam1_time + offset_sec``. A positive offset means cam2's
    recording has more lead-in before the shared moment (it started rolling
    earlier); a negative offset means cam2 started later.
    """

    if len(cam1_samples) == 0 or len(cam2_samples) == 0:
        raise ValueError("cannot sync empty audio")

    a = cam1_samples - cam1_samples.mean()
    b = cam2_samples - cam2_samples.mean()

    corr = correlate(b, a, mode="full", method="fft")
    lags = np.arange(-(len(a) - 1), len(b))

    if max_offset_sec is not None:
        max_lag = int(max_offset_sec * sample_rate)
        mask = np.abs(lags) <= max_lag
        corr = corr[mask]
        lags = lags[mask]
        if len(corr) == 0:
            raise ValueError("max_offset_sec excluded every possible lag")

    best_lag = lags[int(np.argmax(corr))]
    return best_lag / sample_rate


def find_sync_offset(
    cam1_path: str,
    cam2_path: str,
    analysis_window_sec: float = 300.0,
    max_offset_sec: Optional[float] = None,
    sample_rate: int = 16000,
    temp_dir: Optional[str] = None,
) -> float:
    """High-level entry point: extract audio from the start of each camera
    file and find the sync offset between them.

    Only the first ``analysis_window_sec`` seconds of each file are used
    (clamped to the file's own duration) -- syncing doesn't need the whole
    take, just enough shared audio to find a confident correlation peak.
    """

    cam1_duration = min(analysis_window_sec, probe_duration(cam1_path))
    cam2_duration = min(analysis_window_sec, probe_duration(cam2_path))

    cam1_wav = extract_audio_segment(cam1_path, 0.0, cam1_duration, sample_rate, temp_dir)
    try:
        cam2_wav = extract_audio_segment(cam2_path, 0.0, cam2_duration, sample_rate, temp_dir)
        try:
            cam1_samples, sr1 = read_wav_mono(cam1_wav)
            cam2_samples, sr2 = read_wav_mono(cam2_wav)
            assert sr1 == sr2 == sample_rate
            return find_offset_seconds(cam1_samples, cam2_samples, sample_rate, max_offset_sec)
        finally:
            import os

            os.remove(cam2_wav)
    finally:
        import os

        os.remove(cam1_wav)
