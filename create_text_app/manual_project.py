"""Save/load a manual-dictation project (video path + segments) as JSON.

Without this, only the final export (SRT/XML) survives closing the app --
in-progress work (segment timing + dictated text not yet exported) would
be lost. This lets that work be picked back up later.
"""

import json
from typing import List, Tuple

from create_text_app.subtitles import Segment

PROJECT_VERSION = 1


def project_to_dict(
    video_path: str,
    fps: float,
    duration: float,
    dimensions: Tuple[int, int],
    segments: List[Segment],
) -> dict:
    return {
        "version": PROJECT_VERSION,
        "video_path": video_path,
        "fps": fps,
        "duration": duration,
        "dimensions": list(dimensions),
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in segments],
    }


def save_project(
    path: str,
    video_path: str,
    fps: float,
    duration: float,
    dimensions: Tuple[int, int],
    segments: List[Segment],
) -> None:
    data = project_to_dict(video_path, fps, duration, dimensions, segments)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_project(path: str) -> dict:
    """Return ``{video_path, fps, duration, dimensions, segments}``.
    Missing fields fall back to sane defaults rather than raising, so an
    edited-by-hand or older-version project file still loads.
    """

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    segments = [
        Segment(start=float(s["start"]), end=float(s["end"]), text=str(s.get("text", "")))
        for s in data.get("segments", [])
    ]
    dims = data.get("dimensions") or [1920, 1080]

    return {
        "video_path": data.get("video_path"),
        "fps": float(data.get("fps", 30.0)),
        "duration": float(data.get("duration", 0.0)),
        "dimensions": (int(dims[0]), int(dims[1])),
        "segments": segments,
    }
