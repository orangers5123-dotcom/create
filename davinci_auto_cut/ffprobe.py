"""Small ffprobe wrappers for reading duration/fps off a media file."""

import subprocess
from fractions import Fraction

from davinci_auto_cut.ffmpeg_locate import locate


class FfprobeError(RuntimeError):
    pass


def _run_ffprobe(args) -> str:
    cmd = [locate("ffprobe"), "-v", "error", *args]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise FfprobeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace").strip()


def probe_duration(file_path: str) -> float:
    out = _run_ffprobe(
        ["-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
    )
    return float(out)


def parse_frame_rate(raw: str) -> float:
    """Parse ffprobe's ``r_frame_rate`` output, e.g. "30000/1001" or "25/1"."""

    return float(Fraction(raw))


def probe_fps(file_path: str) -> float:
    out = _run_ffprobe(
        [
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
    )
    return parse_frame_rate(out)


def probe_dimensions(file_path: str):
    """Return ``(width, height)`` of a file's first video stream."""

    out = _run_ffprobe(
        [
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1",
            file_path,
        ]
    )
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return int(values["width"]), int(values["height"])
