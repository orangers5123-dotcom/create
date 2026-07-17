import os

import pytest

from silence_cut_app.fcp7_xml import (
    PlacedClip,
    build_fcp7_xml,
    fps_to_timebase,
    parse_fcp7_sequence,
    path_to_pathurl,
    pathurl_to_path,
    timebase_to_fps,
)


def test_timebase_fps_roundtrip_ntsc():
    fps = timebase_to_fps(30, ntsc=True)
    assert fps == pytest.approx(29.97002997002997)
    timebase, ntsc = fps_to_timebase(fps)
    assert (timebase, ntsc) == (30, True)


def test_timebase_fps_roundtrip_integer():
    fps = timebase_to_fps(25, ntsc=False)
    assert fps == 25.0
    timebase, ntsc = fps_to_timebase(fps)
    assert (timebase, ntsc) == (25, False)


def test_pathurl_roundtrip_with_spaces():
    path = "/Users/editor/My Movies/clip 01.mp4"
    url = path_to_pathurl(path)
    assert url.startswith("file://localhost")
    assert pathurl_to_path(url) == path


def test_build_and_parse_single_track_roundtrip(tmp_path):
    fps = 25.0
    clips = [
        PlacedClip("/media/a.mp4", 0.0, 5.0),
        PlacedClip("/media/b.mp4", 2.0, 10.0),
    ]

    xml_str = build_fcp7_xml("My Sequence", fps, [clips])
    xml_path = tmp_path / "seq.xml"
    xml_path.write_text(xml_str, encoding="utf-8")

    parsed_fps, parsed_clips = parse_fcp7_sequence(str(xml_path))

    assert parsed_fps == fps
    assert [c.file_path for c in parsed_clips] == ["/media/a.mp4", "/media/b.mp4"]
    assert parsed_clips[0].source_start_sec == pytest.approx(0.0)
    assert parsed_clips[0].source_duration_sec == pytest.approx(5.0)
    assert parsed_clips[1].source_start_sec == pytest.approx(2.0)
    assert parsed_clips[1].source_duration_sec == pytest.approx(8.0)


def test_build_two_track_xml_has_two_video_and_audio_tracks(tmp_path):
    fps = 25.0
    track1 = [PlacedClip("/media/cam1.mp4", 0.0, 5.0)]
    track2 = [PlacedClip("/media/cam2.mp4", 1.0, 6.0)]

    xml_str = build_fcp7_xml("Two Cam", fps, [track1, track2])
    xml_path = tmp_path / "seq.xml"
    xml_path.write_text(xml_str, encoding="utf-8")

    import xml.etree.ElementTree as ET

    root = ET.parse(str(xml_path)).getroot()
    video_tracks = root.findall(".//sequence/media/video/track")
    audio_tracks = root.findall(".//sequence/media/audio/track")
    assert len(video_tracks) == 2
    assert len(audio_tracks) == 2


def test_shared_file_is_only_defined_once(tmp_path):
    fps = 25.0
    clips = [
        PlacedClip("/media/a.mp4", 0.0, 2.0),
        PlacedClip("/media/a.mp4", 3.0, 4.0),
    ]
    xml_str = build_fcp7_xml("Seq", fps, [clips])

    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_str)
    # The same file is used by 2 video clipitems + 2 linked audio clipitems,
    # but should only be fully <file>-defined (with a pathurl) once; every
    # other clipitem just references that file's id.
    pathurls = root.findall(".//pathurl")
    assert len(pathurls) == 1
