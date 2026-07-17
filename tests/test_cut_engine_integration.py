"""Integration tests that exercise the real ffmpeg/ffprobe pipeline end to
end: generate tiny synthetic clips with a known silence/tone pattern, run
the actual cut engine against them, and check the resulting FCP7 XML.

Skipped automatically if ffmpeg/ffprobe aren't on PATH.
"""

import shutil
import subprocess

import pytest

from silence_cut_app import cut_engine
from silence_cut_app.fcp7_xml import parse_fcp7_sequence

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available on PATH",
)


def _run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


@pytest.fixture
def cam1_cam2(tmp_path):
    """cam1: 2s tone, 4s silence, 2s tone (8s total).
    cam2: same audio content, but with 1s extra lead-in silence and 0.5s
    trailing silence -- i.e. cam2 started rolling 1s before cam1.
    """

    shared_audio = tmp_path / "shared.wav"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[aout]",
            "-map", "[aout]", "-ar", "16000", "-ac", "1",
            str(shared_audio),
        ]
    )

    cam1 = tmp_path / "cam1.mp4"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=8",
            "-i", str(shared_audio),
            "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            str(cam1),
        ]
    )

    cam2_audio = tmp_path / "cam2.wav"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
            "-i", str(shared_audio),
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=0.5",
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[aout]",
            "-map", "[aout]", "-ar", "16000", "-ac", "1",
            str(cam2_audio),
        ]
    )
    cam2 = tmp_path / "cam2.mp4"
    _run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=9.5",
            "-i", str(cam2_audio),
            "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            str(cam2),
        ]
    )

    return str(cam1), str(cam2)


def test_run_single_track_cuts_the_middle_silence(cam1_cam2, tmp_path):
    cam1, _cam2 = cam1_cam2
    output_xml = tmp_path / "out.xml"

    result = cut_engine.run_single_track(
        intensity="standard",
        output_xml_path=str(output_xml),
        source_files=[cam1],
    )

    assert result.total_input_sec == pytest.approx(8.0, abs=0.05)
    # Should keep roughly the two 2s tone segments (a bit of padding on each).
    assert 3.5 < result.total_output_sec < 4.5
    assert result.num_cuts == 1
    assert output_xml.exists()

    fps, clips = parse_fcp7_sequence(str(output_xml))
    assert fps == pytest.approx(25.0)
    assert len(clips) == 2
    assert all(c.file_path == cam1 for c in clips)


def test_run_two_camera_syncs_and_cuts_both_tracks(cam1_cam2, tmp_path):
    cam1, cam2 = cam1_cam2
    output_xml = tmp_path / "out_2cam.xml"

    result = cut_engine.run_two_camera(
        cam1_path=cam1,
        cam2_path=cam2,
        intensity="standard",
        output_xml_path=str(output_xml),
    )

    assert not result.warnings
    assert output_xml.exists()

    import xml.etree.ElementTree as ET

    root = ET.parse(str(output_xml)).getroot()
    video_tracks = root.findall(".//sequence/media/video/track")
    assert len(video_tracks) == 2

    cam1_clips = video_tracks[0].findall("./clipitem")
    cam2_clips = video_tracks[1].findall("./clipitem")
    assert len(cam1_clips) == len(cam2_clips) == 2

    # cam2 was built with ~1s more lead-in than cam1, so every cam2 clipitem's
    # "in" frame should be ~1s (at 25fps, 25 frames) later than cam1's.
    for c1, c2 in zip(cam1_clips, cam2_clips):
        in1 = int(c1.findtext("in"))
        in2 = int(c2.findtext("in"))
        assert in2 - in1 == pytest.approx(25, abs=1)
        # Both tracks must place their matching clip at the same timeline position.
        assert c1.findtext("start") == c2.findtext("start")
        assert c1.findtext("end") == c2.findtext("end")
