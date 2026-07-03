from davinci_auto_cut.ffprobe import parse_frame_rate


def test_parse_frame_rate_fraction():
    assert parse_frame_rate("30000/1001") == 30000 / 1001


def test_parse_frame_rate_whole_number():
    assert parse_frame_rate("25/1") == 25.0
