"""Local speech-to-text via faster-whisper.

Runs entirely on-device (CPU) -- no network calls once the model weights
are cached locally (faster-whisper downloads them from Hugging Face Hub
the first time a given model size is used).
"""

import os
from typing import Callable, List, Optional

from davinci_auto_cut.audio_extract import extract_audio_segment
from davinci_auto_cut.ffprobe import probe_duration

from create_text_app.subtitles import Segment, format_srt_timestamp
from create_text_app.whisper_model import get_model

ProgressCallback = Optional[Callable[[str], None]]

MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]
DEFAULT_MODEL_SIZE = "small"

LANGUAGE_AUTO = "auto"
LANGUAGE_OPTIONS = {
    "自動検出": LANGUAGE_AUTO,
    "日本語": "ja",
    "English": "en",
}


def _log(progress_cb: ProgressCallback, message: str) -> None:
    if progress_cb is not None:
        progress_cb(message)


def transcribe(
    file_path: str,
    model_size: str = DEFAULT_MODEL_SIZE,
    language: str = LANGUAGE_AUTO,
    temp_dir: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> List[Segment]:
    """Transcribe ``file_path`` (video or audio) into a list of ``Segment``.

    ``language`` is a BCP-47-ish code (e.g. "ja", "en") or ``LANGUAGE_AUTO``
    to let Whisper detect it from the first few seconds of audio.
    """

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            "文字起こしには 'faster-whisper' パッケージが必要です。"
            " pip install faster-whisper でインストールしてください。"
        ) from exc

    _log(progress_cb, "音声を抽出中...")
    duration_sec = probe_duration(file_path)
    wav_path = extract_audio_segment(file_path, 0.0, duration_sec, sample_rate=16000, temp_dir=temp_dir)

    try:
        _log(progress_cb, f"Whisperモデル（{model_size}）を読み込み中...（初回はダウンロードが発生します）")
        model = get_model(model_size)

        _log(progress_cb, "文字起こし中...")
        transcribe_kwargs = {}
        if language != LANGUAGE_AUTO:
            transcribe_kwargs["language"] = language

        raw_segments, info = model.transcribe(wav_path, vad_filter=True, **transcribe_kwargs)

        if language == LANGUAGE_AUTO:
            _log(progress_cb, f"検出された言語: {info.language} (確信度 {info.language_probability:.0%})")

        segments: List[Segment] = []
        for raw in raw_segments:
            seg = Segment(start=raw.start, end=raw.end, text=raw.text.strip())
            segments.append(seg)
            _log(progress_cb, f"[{format_srt_timestamp(seg.start)}] {seg.text}")

        return segments
    finally:
        os.remove(wav_path)
