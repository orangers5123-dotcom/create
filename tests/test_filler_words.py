from davinci_auto_cut.filler_words import WordTiming, find_filler_intervals, normalize

FILLER_WORDS = ["えー", "あの", "you know", "um"]


def words(*specs):
    # specs like ("えー", 0.0, 0.3)
    return [WordTiming(word=w, start=s, end=e) for w, s, e in specs]


def test_normalize_strips_punctuation_and_lowercases():
    assert normalize("Um,") == "um"
    assert normalize("えー。") == "えー"


def test_single_word_filler_matched():
    w = words(("えー", 0.0, 0.3), ("今日は", 0.3, 0.8))
    assert find_filler_intervals(w, FILLER_WORDS) == [(0.0, 0.3)]


def test_multi_word_phrase_filler_matched():
    w = words(("you", 1.0, 1.2), ("know", 1.2, 1.5), ("what", 1.5, 1.8))
    assert find_filler_intervals(w, FILLER_WORDS) == [(1.0, 1.5)]


def test_no_fillers_present():
    w = words(("hello", 0.0, 0.5), ("world", 0.5, 1.0))
    assert find_filler_intervals(w, FILLER_WORDS) == []


def test_multiple_fillers_in_sequence():
    w = words(
        ("えー", 0.0, 0.3),
        ("あの", 0.4, 0.6),
        ("本題", 0.6, 1.0),
    )
    assert find_filler_intervals(w, FILLER_WORDS) == [(0.0, 0.3), (0.4, 0.6)]


def test_prefers_longer_phrase_match_over_single_word():
    # "um" alone is a filler, but here we only have the two-word phrase.
    w = words(("you", 0.0, 0.2), ("know", 0.2, 0.4))
    assert find_filler_intervals(w, FILLER_WORDS) == [(0.0, 0.4)]
