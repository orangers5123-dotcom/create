from davinci_auto_cut.silence import parse_silencedetect_output

SAMPLE_STDERR = """\
[silencedetect @ 0x7f9] silence_start: 1.23456
[silencedetect @ 0x7f9] silence_end: 2.5 | silence_duration: 1.26544
[silencedetect @ 0x7f9] silence_start: 8.0
[silencedetect @ 0x7f9] silence_end: 9.75 | silence_duration: 1.75
"""


def test_parse_silencedetect_output_basic():
    intervals = parse_silencedetect_output(SAMPLE_STDERR)
    assert intervals == [(1.23456, 2.5), (8.0, 9.75)]


def test_parse_silencedetect_output_no_matches():
    assert parse_silencedetect_output("nothing relevant here") == []


def test_parse_silencedetect_output_empty():
    assert parse_silencedetect_output("") == []
