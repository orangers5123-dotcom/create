"""Compute a simple peak-based waveform for display: downsample a video's
full audio track into a small number of per-bin peak amplitudes (0..1),
cheap enough to draw as a bar waveform under the manual mode's scrub
slider, so IN/OUT points can be lined up against the audio visually
instead of only by ear/blind scrubbing.
"""

import os
from typing import List, Optional

from davinci_auto_cut.audio_extract import extract_audio_segment


def extract_waveform_peaks(video_path: str, duration_sec: float, num_points: int = 400, temp_dir: Optional[str] = None) -> List[float]:
    """Return ``num_points`` peak amplitudes (0..1) spanning the whole of
    ``video_path``'s audio, one per evenly-sized time bin.
    """

    if duration_sec <= 0 or num_points <= 0:
        return []

    wav_path = extract_audio_segment(video_path, 0.0, duration_sec, sample_rate=8000, temp_dir=temp_dir)
    try:
        import numpy as np
        from scipy.io import wavfile

        _samplerate, data = wavfile.read(wav_path)
        if data.ndim > 1:
            data = data[:, 0]
        data = data.astype(np.float32)

        if len(data) == 0:
            return [0.0] * num_points

        max_abs = float(np.max(np.abs(data)))
        if max_abs == 0.0:
            return [0.0] * num_points
        data = data / max_abs

        bin_size = max(len(data) // num_points, 1)
        peaks = []
        for i in range(num_points):
            chunk = data[i * bin_size : i * bin_size + bin_size]
            peaks.append(float(np.max(np.abs(chunk))) if len(chunk) else 0.0)
        return peaks
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
