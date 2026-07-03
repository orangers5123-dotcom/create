"""Extract a source clip's audio to a mono WAV file via ffmpeg."""

import os
import subprocess
import tempfile


class FfmpegError(RuntimeError):
    pass


def extract_audio_segment(
    file_path: str,
    start_sec: float,
    duration_sec: float,
    sample_rate: int = 16000,
    temp_dir: str = None,
) -> str:
    """Extract ``duration_sec`` seconds of audio starting at ``start_sec``
    from ``file_path`` into a new mono WAV file, and return its path.

    The caller is responsible for deleting the returned file when done.
    """

    if duration_sec <= 0:
        raise ValueError(f"duration_sec must be positive, got {duration_sec}")

    fd, out_path = tempfile.mkstemp(suffix=".wav", dir=temp_dir, prefix="davinci_auto_cut_")
    os.close(fd)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_sec:.6f}",
        "-i", file_path,
        "-t", f"{duration_sec:.6f}",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-vn",
        out_path,
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise FfmpegError(
            f"ffmpeg failed extracting audio from {file_path!r}: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )

    return out_path
