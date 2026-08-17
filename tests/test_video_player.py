import shutil
import subprocess

import pytest

pytest.importorskip("cv2")

from create_text_app.video_player import VideoFrameReader, VideoFrameReaderError

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


def test_read_frame_at_returns_correctly_sized_image(synthetic_video):
    reader = VideoFrameReader(synthetic_video)
    try:
        frame = reader.read_frame_at(1.0)
        assert frame is not None
        assert frame.size == (320, 240)
        assert frame.mode == "RGB"
    finally:
        reader.close()


def test_read_frame_at_negative_time_clamped_to_zero(synthetic_video):
    reader = VideoFrameReader(synthetic_video)
    try:
        frame = reader.read_frame_at(-5.0)
        assert frame is not None
    finally:
        reader.close()


def test_read_frame_at_can_seek_backwards_and_forwards(synthetic_video):
    reader = VideoFrameReader(synthetic_video)
    try:
        assert reader.read_frame_at(2.0) is not None
        assert reader.read_frame_at(0.5) is not None
        assert reader.read_frame_at(1.5) is not None
    finally:
        reader.close()


def test_open_nonexistent_file_raises():
    with pytest.raises(VideoFrameReaderError):
        VideoFrameReader("/nonexistent/video.mp4")
