"""Turn a set of "cut" intervals (silence, filler words, ...) into the
list of segments to keep. Pure functions, no Resolve/ffmpeg dependency.
"""

from typing import List, Tuple

Interval = Tuple[float, float]


def merge_intervals(intervals: List[Interval]) -> List[Interval]:
    """Sort and merge overlapping/touching ``(start, end)`` intervals."""

    if not intervals:
        return []

    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def complement_intervals(cut_intervals: List[Interval], total_duration: float) -> List[Interval]:
    """Segments of ``[0, total_duration]`` not covered by ``cut_intervals``."""

    keep: List[Interval] = []
    cursor = 0.0
    for start, end in merge_intervals(cut_intervals):
        start = max(0.0, min(start, total_duration))
        end = max(0.0, min(end, total_duration))
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_duration:
        keep.append((cursor, total_duration))
    return keep


def intervals_to_keep_segments(
    total_duration: float,
    cut_intervals: List[Interval],
    padding: float = 0.0,
    min_keep_duration: float = 0.0,
) -> List[Interval]:
    """Given intervals to cut out of ``[0, total_duration]``, return the
    segments that should be kept.

    ``padding`` shrinks each cut interval by that many seconds on both
    sides, so a bit of the silence/pause is left in place rather than
    every cut landing exactly on the detected boundary.

    ``min_keep_duration`` folds any resulting keep-segment shorter than
    this back into the surrounding cuts, so a one-frame sliver of a clip
    doesn't survive between two adjacent cuts.
    """

    if total_duration <= 0:
        return []

    shrunk: List[Interval] = []
    for start, end in merge_intervals(cut_intervals):
        s = start + padding
        e = end - padding
        if e > s:
            shrunk.append((max(0.0, s), min(total_duration, e)))

    keep = complement_intervals(shrunk, total_duration)

    too_short = [seg for seg in keep if (seg[1] - seg[0]) < min_keep_duration]
    if too_short:
        shrunk = merge_intervals(shrunk + too_short)
        keep = complement_intervals(shrunk, total_duration)

    return keep
