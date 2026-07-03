"""Import a source video file into Resolve's Media Pool and lay the
computed keep-segments onto a timeline, in order.

Unlike ``editor.py`` (which cuts clips that are already on a timeline),
this is for the "here's a file on disk, cut it and build the timeline"
workflow: nothing needs to be deleted since nothing is on the timeline
yet -- ``MediaPool.AppendToTimeline`` creates a timeline automatically if
the project doesn't have a current one.

Written strictly against the documented scripting API; not
execution-tested (no Resolve instance in this sandbox).
"""

from typing import List, Tuple

Interval = Tuple[float, float]


class MediaImportError(RuntimeError):
    pass


def import_media(media_pool, file_path: str):
    items = media_pool.ImportMedia([file_path])
    if not items:
        raise MediaImportError(f"Resolve refused to import: {file_path}")
    return items[0]


def get_clip_fps(media_pool_item, fallback_fps: float) -> float:
    raw = media_pool_item.GetClipProperty("FPS")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback_fps


def build_clip_infos(media_pool_item, keep_segments_sec: List[Interval], fps: float) -> List[dict]:
    clip_infos = []
    for seg_start_sec, seg_end_sec in keep_segments_sec:
        start_frame = round(seg_start_sec * fps)
        end_frame = round(seg_end_sec * fps) - 1
        if end_frame <= start_frame:
            continue
        clip_infos.append(
            {
                "mediaPoolItem": media_pool_item,
                "startFrame": start_frame,
                "endFrame": end_frame,
            }
        )
    return clip_infos


def append_files_to_timeline(
    media_pool,
    files_with_keep_segments: List[Tuple[str, List[Interval]]],
    fallback_fps: float = 24.0,
) -> List[dict]:
    """Import each file in order and append its keep-segments to the
    timeline, back to back, in the order the files were given.
    """

    all_clip_infos: List[dict] = []
    for file_path, keep_segments in files_with_keep_segments:
        media_pool_item = import_media(media_pool, file_path)
        fps = get_clip_fps(media_pool_item, fallback_fps)
        all_clip_infos.extend(build_clip_infos(media_pool_item, keep_segments, fps))

    if all_clip_infos:
        media_pool.AppendToTimeline(all_clip_infos)

    return all_clip_infos
