import pytest

from create_text_app.subtitles import (
    Segment,
    build_srt,
    build_txt,
    build_vtt,
    format_srt_timestamp,
    format_vtt_timestamp,
    parse_srt,
)


def test_format_srt_timestamp_basic():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(1.5) == "00:00:01,500"
    assert format_srt_timestamp(61.25) == "00:01:01,250"
    assert format_srt_timestamp(3661.001) == "01:01:01,001"


def test_format_srt_timestamp_negative_clamped_to_zero():
    assert format_srt_timestamp(-1.0) == "00:00:00,000"


def test_format_vtt_timestamp_uses_period():
    assert format_vtt_timestamp(1.5) == "00:00:01.500"


def test_build_srt_basic():
    segments = [
        Segment(0.0, 2.5, "Hello world"),
        Segment(2.5, 5.0, "Next segment"),
    ]
    srt = build_srt(segments)
    assert srt == (
        "1\n00:00:00,000 --> 00:00:02,500\nHello world\n"
        "\n"
        "2\n00:00:02,500 --> 00:00:05,000\nNext segment\n"
    )


def test_build_vtt_basic():
    segments = [Segment(0.0, 2.5, "Hello world")]
    vtt = build_vtt(segments)
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.500\nHello world\n" in vtt


def test_build_txt_basic():
    segments = [Segment(0.0, 1.0, "Line one"), Segment(1.0, 2.0, "Line two")]
    assert build_txt(segments) == "Line one\nLine two\n"


def test_empty_text_segments_dropped_from_all_exports():
    segments = [
        Segment(0.0, 1.0, "Keep me"),
        Segment(1.0, 2.0, "   "),  # cleared/deleted by the user
        Segment(2.0, 3.0, ""),
    ]
    srt = build_srt(segments)
    assert "Keep me" in srt
    assert srt.count("-->") == 1  # only one cue survives
    assert srt.startswith("1\n")  # renumbered starting at 1

    vtt = build_vtt(segments)
    assert vtt.count("-->") == 1

    assert build_txt(segments) == "Keep me\n"


def test_build_functions_handle_empty_list():
    assert build_srt([]) == ""
    assert build_vtt([]) == "WEBVTT\n"
    assert build_txt([]) == ""


def test_parse_srt_basic():
    srt_text = (
        "1\n00:00:00,000 --> 00:00:02,500\nHello world\n"
        "\n"
        "2\n00:00:02,500 --> 00:00:05,000\nNext segment\n"
    )
    segments = parse_srt(srt_text)
    assert len(segments) == 2
    assert segments[0].start == 0.0
    assert segments[0].end == 2.5
    assert segments[0].text == "Hello world"
    assert segments[1].start == 2.5
    assert segments[1].end == 5.0
    assert segments[1].text == "Next segment"


def test_parse_srt_round_trips_through_build_srt():
    original = [Segment(0.0, 2.5, "Hello world"), Segment(2.5, 5.0, "Next segment")]
    reparsed = parse_srt(build_srt(original))
    assert [(round(s.start, 3), round(s.end, 3), s.text) for s in reparsed] == [
        (0.0, 2.5, "Hello world"),
        (2.5, 5.0, "Next segment"),
    ]


def test_parse_srt_joins_multiline_cue_text_with_spaces():
    srt_text = "1\n00:00:01,000 --> 00:00:03,000\nLine one\nLine two\n"
    segments = parse_srt(srt_text)
    assert segments[0].text == "Line one Line two"


def test_parse_srt_tolerates_missing_index_line():
    srt_text = "00:00:01,000 --> 00:00:03,000\nNo index line here\n"
    segments = parse_srt(srt_text)
    assert len(segments) == 1
    assert segments[0].text == "No index line here"


def test_parse_srt_accepts_period_before_milliseconds():
    srt_text = "1\n00:00:01.000 --> 00:00:03.000\nPeriod separator\n"
    segments = parse_srt(srt_text)
    assert len(segments) == 1
    assert segments[0].start == 1.0


def test_parse_srt_handles_empty_and_malformed_input():
    assert parse_srt("") == []
    assert parse_srt("not an srt file at all") == []


def test_parse_srt_handles_cue_with_no_text():
    srt_text = "1\n00:00:01,000 --> 00:00:03,000\n"
    segments = parse_srt(srt_text)
    assert len(segments) == 1
    assert segments[0].text == ""
