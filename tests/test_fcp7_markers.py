import xml.etree.ElementTree as ET

from create_text_app.fcp7_markers import build_marker_xml, _marker_name
from create_text_app.subtitles import Segment


def _parse(xml_str):
    return ET.fromstring(xml_str)


def test_build_marker_xml_has_one_clip_spanning_the_whole_video():
    segments = [Segment(start=1.0, end=2.0, text="hello")]
    xml_str = build_marker_xml("Seq", 30.0, "/videos/cam.mp4", 10.0, segments)
    root = _parse(xml_str)

    sequence = root.find(".//sequence")
    assert sequence.findtext("duration") == "300"  # 10s * 30fps

    v_clip = sequence.find("./media/video/track/clipitem")
    assert v_clip.findtext("in") == "0"
    assert v_clip.findtext("out") == "300"
    assert v_clip.find("./file").findtext("pathurl").endswith("cam.mp4")

    a_clip = sequence.find("./media/audio/track/clipitem")
    assert a_clip.findtext("out") == "300"


def test_build_marker_xml_writes_one_marker_per_segment():
    segments = [
        Segment(start=1.0, end=2.0, text="one"),
        Segment(start=5.0, end=6.5, text="two"),
    ]
    xml_str = build_marker_xml("Seq", 30.0, "/videos/cam.mp4", 10.0, segments)
    root = _parse(xml_str)

    markers = root.findall(".//sequence/marker")
    assert len(markers) == 2
    assert markers[0].findtext("name") == "one"
    assert markers[0].findtext("in") == "30"
    assert markers[0].findtext("out") == "60"
    assert markers[1].findtext("in") == "150"
    assert markers[1].findtext("out") == "195"


def test_build_marker_xml_skips_empty_text_segments():
    segments = [
        Segment(start=1.0, end=2.0, text="   "),
        Segment(start=5.0, end=6.0, text="kept"),
    ]
    xml_str = build_marker_xml("Seq", 30.0, "/videos/cam.mp4", 10.0, segments)
    root = _parse(xml_str)

    markers = root.findall(".//sequence/marker")
    assert len(markers) == 1
    assert markers[0].findtext("name") == "kept"


def test_marker_name_truncates_long_text():
    long_text = "a" * 100
    name = _marker_name(long_text)
    assert len(name) <= 60
    assert name.endswith("…")


def test_marker_name_collapses_whitespace():
    assert _marker_name("hello\n\nworld   foo") == "hello world foo"
