"""Pure-logic subtitle export: build SRT / VTT / plain-text output from a
list of transcript segments. No Whisper dependency -- easy to unit test.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Segment:
    start: float  # seconds
    end: float
    text: str


def format_srt_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm`` -- SRT uses a comma before milliseconds."""

    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    """``HH:MM:SS.mmm`` -- VTT uses a period before milliseconds."""

    return format_srt_timestamp(seconds).replace(",", ".")


def _non_empty(segments: List[Segment]) -> List[Segment]:
    """Segments whose text was cleared (e.g. deleted in the editor) are
    dropped from every export -- an empty cue isn't meaningful output.
    """

    return [seg for seg in segments if seg.text.strip()]


def build_srt(segments: List[Segment]) -> str:
    blocks = []
    for i, seg in enumerate(_non_empty(segments), start=1):
        blocks.append(
            f"{i}\n"
            f"{format_srt_timestamp(seg.start)} --> {format_srt_timestamp(seg.end)}\n"
            f"{seg.text}\n"
        )
    return "\n".join(blocks)


def build_vtt(segments: List[Segment]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in _non_empty(segments):
        blocks.append(
            f"{format_vtt_timestamp(seg.start)} --> {format_vtt_timestamp(seg.end)}\n"
            f"{seg.text}\n"
        )
    return "\n".join(blocks)


def build_txt(segments: List[Segment]) -> str:
    """A clean transcript: just the text, one segment per line, no timestamps."""

    kept = _non_empty(segments)
    return "\n".join(seg.text for seg in kept) + ("\n" if kept else "")
