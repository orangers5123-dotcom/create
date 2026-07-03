"""Read clip geometry off the current timeline.

Like resolve_connect.py, this talks to the live Resolve API objects and
cannot be exercised in this sandbox (no Resolve install here). The frame
math follows the conventions used by Blackmagic's own scripting examples
and by community Resolve scripts:

- ``TimelineItem.GetStart()`` / ``GetEnd()`` are *record* frames: absolute
  positions on the timeline.
- ``TimelineItem.GetLeftOffset()`` is the *source* in-frame -- how far
  into the underlying media the clip's visible content starts. Source
  out-frame is therefore ``left_offset + duration - 1``.

Verify these against a real timeline before trusting them on anything
irreplaceable -- see README.md "Testing notes".
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TimelineClip:
    item: object  # the raw Resolve TimelineItem
    track_index: int
    name: str
    file_path: Optional[str]
    fps: float

    record_start: int  # absolute frame on the timeline
    record_end: int

    source_start: int  # frame within the source media
    source_end: int

    @property
    def record_duration(self) -> int:
        return self.record_end - self.record_start

    @property
    def timeline_start_sec(self) -> float:
        return self.record_start / self.fps

    @property
    def source_start_sec(self) -> float:
        return self.source_start / self.fps

    @property
    def source_duration_sec(self) -> float:
        return (self.source_end - self.source_start) / self.fps


def get_timeline_fps(timeline) -> float:
    raw = timeline.GetSetting("timelineFrameRate")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 24.0


def get_video_items(timeline, track_index: int = 1) -> List[TimelineClip]:
    """Return every clip on the given (1-based) video track, in order."""

    fps = get_timeline_fps(timeline)
    raw_items = timeline.GetItemListInTrack("video", track_index) or []

    clips: List[TimelineClip] = []
    for item in raw_items:
        media_pool_item = item.GetMediaPoolItem()
        file_path = None
        if media_pool_item is not None:
            file_path = media_pool_item.GetClipProperty("File Path") or None

        record_start = item.GetStart()
        record_end = item.GetEnd()
        duration = item.GetDuration()
        left_offset = item.GetLeftOffset()

        clips.append(
            TimelineClip(
                item=item,
                track_index=track_index,
                name=item.GetName(),
                file_path=file_path,
                fps=fps,
                record_start=record_start,
                record_end=record_end,
                source_start=left_offset,
                source_end=left_offset + duration - 1,
            )
        )

    clips.sort(key=lambda c: c.record_start)
    return clips
