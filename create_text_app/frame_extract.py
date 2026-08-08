"""Grab a single video frame as a PNG via ffmpeg, for the manual-captioning
preview (a scrub-and-look preview, not real-time video playback).
"""

import os
import subprocess
import tempfile

from davinci_auto_cut.ffmpeg_locate import locate


class FrameExtractError(RuntimeError):
    pass


def extract_frame(video_path: str, time_sec: float, out_path: str = None, temp_dir: str = None) -> str:
    """Extract the frame at ``time_sec`` from ``video_path`` into a PNG file
    and return its path. If ``out_path`` isn't given, a new temp file is
    created -- the caller is responsible for deleting it when done.
    """

    if time_sec < 0:
        time_sec = 0.0

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".png", dir=temp_dir, prefix="create_text_frame_")
        os.close(fd)

    cmd = [
        locate("ffmpeg"),
        "-y",
        "-ss", f"{time_sec:.6f}",
        "-i", video_path,
        "-frames:v", "1",
        "-f", "image2",
        out_path,
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise FrameExtractError(
            f"ffmpeg failed extracting a frame from {video_path!r} at {time_sec:.3f}s: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )

    return out_path
