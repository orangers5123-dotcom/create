"""Configuration for the auto-cut skill."""

from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_FILLER_WORDS_JA = [
    "えー", "えーと", "えっと", "あの", "あのー", "あのう",
    "まあ", "まぁ", "なんか", "そのー", "そのう", "ええと", "うーん", "うん",
]

DEFAULT_FILLER_WORDS_EN = [
    "um", "uh", "uhh", "umm", "erm", "you know", "i mean", "like",
]


@dataclass
class AutoCutConfig:
    # -- Which track to process --
    # DaVinci Resolve track indices are 1-based.
    target_video_track: int = 1

    # -- Silence detection --
    enable_silence_cut: bool = True
    silence_threshold_db: float = -35.0
    min_silence_duration: float = 0.4  # seconds

    # -- Filler word removal (Google Cloud Speech-to-Text) --
    enable_filler_word_removal: bool = False
    filler_words: List[str] = field(
        default_factory=lambda: [*DEFAULT_FILLER_WORDS_JA, *DEFAULT_FILLER_WORDS_EN]
    )
    # BCP-47 language code, e.g. "ja-JP" or "en-US". Google STT (unlike
    # Whisper) does not auto-detect language, so this must be set correctly.
    google_language_code: str = "ja-JP"
    # The synchronous Speech-to-Text `recognize` call caps out at ~1 minute
    # of audio per request, so long clips are split into chunks this long
    # (seconds) before sending each one off for transcription.
    google_chunk_seconds: float = 55.0

    # -- Cut shaping --
    # Seconds of the detected silence/filler interval to leave in place on
    # each side, so cuts don't feel abrupt.
    padding: float = 0.08
    # Keep-segments shorter than this are folded into the surrounding cut
    # instead of being left behind as a tiny sliver of a clip.
    min_keep_duration: float = 0.15

    # -- Safety --
    # When True (default), no edits are made to the timeline. Instead,
    # markers are added at every planned cut so they can be reviewed in
    # Resolve before anything is actually removed.
    dry_run: bool = True

    # -- Working files --
    temp_dir: Optional[str] = None  # None = use system temp dir
    sample_rate: int = 16000
