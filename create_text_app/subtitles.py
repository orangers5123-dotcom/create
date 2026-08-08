"""Pure-logic subtitle export: build SRT / VTT / plain-text output from a
list of transcript segments. No Whisper dependency -- easy to unit test.
"""

import re
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


_SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _srt_timestamp_to_seconds(hh: str, mm: str, ss: str, ms: str) -> float:
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0


def parse_srt(text: str) -> List[Segment]:
    """Parse SRT-formatted text into a list of ``Segment``, for loading an
    existing subtitle file into manual mode to continue editing/re-dictating.

    Lenient: the leading cue-index line is optional (only the timestamp line
    is actually required to identify a block), blank lines separate cues,
    and both ``,`` and ``.`` are accepted before milliseconds. Multi-line
    cue text is joined with spaces -- segments here are edited in a
    single-line field, so a literal newline wouldn't display usefully.
    """

    segments: List[Segment] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        match = None
        time_line_index = None
        for i, line in enumerate(lines):
            match = _SRT_TIME_RE.search(line)
            if match:
                time_line_index = i
                break
        if match is None:
            continue

        start = _srt_timestamp_to_seconds(*match.groups()[0:4])
        end = _srt_timestamp_to_seconds(*match.groups()[4:8])
        cue_text = " ".join(lines[time_line_index + 1 :]).strip()
        segments.append(Segment(start=start, end=end, text=cue_text))

    return segments
