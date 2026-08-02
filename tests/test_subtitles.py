import pytest

from create_text_app.subtitles import (
    Segment,
    build_srt,
    build_txt,
    build_vtt,
    format_srt_timestamp,
    format_vtt_timestamp,
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
