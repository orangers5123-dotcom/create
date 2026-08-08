import shutil
import subprocess

import pytest

from create_text_app.frame_extract import FrameExtractError, extract_frame

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")


@pytest.fixture
def synthetic_video(tmp_path):
    video = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
            "-pix_fmt", "yuv420p",
            str(video),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return str(video)


def test_extract_frame_writes_a_nonempty_png(synthetic_video, tmp_path):
    out_path = str(tmp_path / "frame.png")
    result = extract_frame(synthetic_video, 1.0, out_path=out_path)

    assert result == out_path
    with open(out_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"


def test_extract_frame_creates_temp_file_when_no_out_path_given(synthetic_video, tmp_path):
    result = extract_frame(synthetic_video, 0.5, temp_dir=str(tmp_path))
    assert result.endswith(".png")
    with open(result, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_extract_frame_negative_time_clamped_to_zero(synthetic_video, tmp_path):
    out_path = str(tmp_path / "frame_neg.png")
    result = extract_frame(synthetic_video, -5.0, out_path=out_path)
    assert result == out_path


def test_extract_frame_raises_on_bad_input_file(tmp_path):
    with pytest.raises(FrameExtractError):
        extract_frame(str(tmp_path / "does_not_exist.mp4"), 0.0, out_path=str(tmp_path / "out.png"))
