from davinci_auto_cut.cutlist import complement_intervals, intervals_to_keep_segments, merge_intervals


def test_merge_intervals_overlapping():
    assert merge_intervals([(0, 2), (1, 3), (5, 6)]) == [(0, 3), (5, 6)]


def test_merge_intervals_touching():
    assert merge_intervals([(0, 2), (2, 4)]) == [(0, 4)]


def test_merge_intervals_empty():
    assert merge_intervals([]) == []


def test_merge_intervals_unsorted_input():
    assert merge_intervals([(5, 6), (0, 1)]) == [(0, 1), (5, 6)]


def test_complement_basic():
    assert complement_intervals([(2, 4)], 10) == [(0, 2), (4, 10)]


def test_complement_covers_whole_range():
    assert complement_intervals([(0, 10)], 10) == []


def test_complement_no_cuts():
    assert complement_intervals([], 10) == [(0, 10)]


def test_keep_segments_basic_silence_cut():
    # 10s clip, silence from 4-6s, no padding/min-keep.
    keep = intervals_to_keep_segments(10, [(4, 6)], padding=0.0, min_keep_duration=0.0)
    assert keep == [(0, 4), (6, 10)]


def test_keep_segments_padding_shrinks_the_cut():
    # Cut is 4-6s but padding=0.5 leaves 0.5s of it on each side.
    keep = intervals_to_keep_segments(10, [(4, 6)], padding=0.5, min_keep_duration=0.0)
    assert keep == [(0, 4.5), (5.5, 10)]


def test_keep_segments_padding_can_eliminate_a_short_cut():
    # A 0.2s silence with 0.5s padding on each side has no room left to cut.
    keep = intervals_to_keep_segments(10, [(4, 4.2)], padding=0.5, min_keep_duration=0.0)
    assert keep == [(0, 10)]


def test_keep_segments_folds_short_keep_into_surrounding_cuts():
    # Two cuts close together leave a sliver of "keep" between them that's
    # shorter than min_keep_duration -- it should be swallowed by the cuts.
    keep = intervals_to_keep_segments(
        10, [(2, 3), (3.05, 5)], padding=0.0, min_keep_duration=0.5
    )
    assert keep == [(0, 2), (5, 10)]


def test_keep_segments_overlapping_cut_intervals_merge_first():
    # Silence and filler-word intervals overlapping should merge cleanly.
    keep = intervals_to_keep_segments(
        10, [(2, 4), (3, 5)], padding=0.0, min_keep_duration=0.0
    )
    assert keep == [(0, 2), (5, 10)]


def test_keep_segments_empty_duration():
    assert intervals_to_keep_segments(0, [(0, 1)]) == []


def test_keep_segments_no_cuts_keeps_everything():
    assert intervals_to_keep_segments(10, []) == [(0, 10)]
