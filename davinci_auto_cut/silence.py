"""Silence detection using ffmpeg's ``silencedetect`` filter."""

import re
import subprocess
from typing import List, Tuple

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[0-9.]+)")


def parse_silencedetect_output(stderr_text: str) -> List[Tuple[float, float]]:
    """Parse ffmpeg ``silencedetect`` stderr into a list of ``(start, end)``
    second pairs. Pure function -- no ffmpeg required, easy to unit test.

    A trailing, unmatched ``silence_start`` (silence runs to the end of the
    file) is dropped: without a real audio duration we cannot safely turn it
    into a keep/cut segment. Callers detecting silence within a bounded clip
    duration should already have the natural end-of-clip as the audio's end.
    """

    starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr_text)]
    ends = [float(m.group(1)) for m in _SILENCE_END_RE.finditer(stderr_text)]

    intervals = list(zip(starts, ends))
    return intervals


def detect_silence(
    wav_path: str,
    threshold_db: float = -35.0,
    min_duration: float = 0.4,
) -> List[Tuple[float, float]]:
    """Run ffmpeg silencedetect on ``wav_path`` and return silence
    intervals as ``(start_sec, end_sec)`` tuples relative to the file.
    """

    cmd = [
        "ffmpeg",
        "-i", wav_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    return parse_silencedetect_output(stderr_text)
