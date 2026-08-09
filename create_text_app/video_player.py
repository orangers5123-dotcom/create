"""Fast video frame reads for the manual-mode preview, backed by OpenCV
instead of shelling out to ffmpeg per frame.

The earlier scrub-only preview (``frame_extract.py``) spawns an ffmpeg
process per frame -- fine for occasional scrubbing, far too slow for
real-time playback (needs ~25-30 reads/second). ``VideoFrameReader`` keeps
one decoder open for the life of a loaded video and seeks/reads from it
directly, which is fast enough to drive both scrubbing and playback.
"""

from typing import Optional

from PIL import Image


class VideoFrameReaderError(RuntimeError):
    pass


class VideoFrameReader:
    def __init__(self, video_path: str):
        try:
            import cv2
        except ImportError as exc:
            raise VideoFrameReaderError(
                "動画再生には 'opencv-python-headless' パッケージが必要です。"
                " pip install opencv-python-headless でインストールしてください。"
            ) from exc

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise VideoFrameReaderError(f"動画を開けませんでした: {video_path!r}")

    def read_frame_at(self, time_sec: float) -> Optional[Image.Image]:
        """Seek to ``time_sec`` and return that frame as a PIL Image, or
        ``None`` if the read failed (e.g. seeking past the end)."""

        if time_sec < 0:
            time_sec = 0.0

        self._cap.set(self._cv2.CAP_PROP_POS_MSEC, time_sec * 1000.0)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None

        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def close(self) -> None:
        self._cap.release()
