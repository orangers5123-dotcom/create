"""Apply a computed cut list to the Resolve timeline.

Two modes:

- ``add_cut_markers`` (used when ``AutoCutConfig.dry_run`` is True): makes
  no structural changes, just drops a marker at every planned cut so you
  can scrub through and sanity-check them in Resolve first.

- ``apply_all_cuts`` (used when ``dry_run`` is False): actually rewrites
  the track. The Resolve scripting API has no "split clip at frame" call,
  so this uses the standard workaround: delete the original clips, then
  re-add the kept sub-ranges via ``MediaPool.AppendToTimeline`` with
  explicit ``startFrame``/``endFrame`` per segment. Deleting *all* target
  clips before appending *any* replacements is deliberate -- appending
  adds after the current last item on the timeline, so interleaving
  delete/append per clip would scramble ordering once more than one clip
  is involved.

As with the other Resolve-facing modules, this is written strictly from
the documented scripting API and has not been execution-tested against a
real Resolve instance.
"""

from typing import List, Tuple

from davinci_auto_cut.timeline_items import TimelineClip

Interval = Tuple[float, float]


def add_cut_markers(timeline, clip: TimelineClip, cut_intervals_sec: List[Interval]) -> int:
    """Add a red marker over each planned cut on ``clip``. Returns the
    number of markers added. ``cut_intervals_sec`` is relative to the
    start of ``clip`` on the timeline.
    """

    timeline_start_frame = timeline.GetStartFrame()
    added = 0
    for start_sec, end_sec in cut_intervals_sec:
        frame = clip.record_start + round(start_sec * clip.fps) - timeline_start_frame
        duration_frames = max(1, round((end_sec - start_sec) * clip.fps))
        ok = timeline.AddMarker(
            frame,
            "Red",
            "Auto-cut (planned)",
            f"{clip.name}: {end_sec - start_sec:.2f}s silence/filler",
            duration_frames,
        )
        if ok:
            added += 1
    return added


def build_clip_infos(clip: TimelineClip, keep_segments_sec: List[Interval]) -> List[dict]:
    media_pool_item = clip.item.GetMediaPoolItem()
    fps = clip.fps

    clip_infos = []
    for seg_start_sec, seg_end_sec in keep_segments_sec:
        start_frame = clip.source_start + round(seg_start_sec * fps)
        end_frame = clip.source_start + round(seg_end_sec * fps) - 1
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


def apply_all_cuts(
    media_pool,
    timeline,
    clips_with_keep_segments: List[Tuple[TimelineClip, List[Interval]]],
) -> List[dict]:
    """Delete every clip in ``clips_with_keep_segments`` and re-append only
    the kept sub-ranges, in original left-to-right order. Returns the list
    of clip-info dicts that were appended.
    """

    items = [clip.item for clip, _ in clips_with_keep_segments]
    if items:
        timeline.DeleteClips(items, True)

    all_clip_infos: List[dict] = []
    for clip, keep_segments in clips_with_keep_segments:
        all_clip_infos.extend(build_clip_infos(clip, keep_segments))

    if all_clip_infos:
        media_pool.AppendToTimeline(all_clip_infos)

    return all_clip_infos
