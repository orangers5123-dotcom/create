"""Cut-intensity presets for the silence auto-cut app.

Each preset maps to the same knobs used by ``davinci_auto_cut.silence`` /
``davinci_auto_cut.cutlist``: how long a quiet stretch has to be before it
counts as "silence", how sensitive the volume threshold is, and how much
padding/slack to leave around cuts so they don't feel abrupt.
"""

from dataclasses import dataclass
from enum import Enum


class Intensity(str, Enum):
    SOFT = "soft"
    STANDARD = "standard"
    HARD = "hard"


@dataclass(frozen=True)
class IntensitySettings:
    label: str
    # ffmpeg silencedetect: dB below which audio counts as silent.
    silence_threshold_db: float
    # Minimum length (seconds) of a quiet stretch to treat as cuttable silence.
    min_silence_duration: float
    # Seconds of the detected silence left in place on each side of a cut.
    padding: float
    # Keep-segments shorter than this are folded into the surrounding cut.
    min_keep_duration: float


# Soft: only cut long silences (6s+), leave generous padding -- safe/conservative.
# Standard: cut silences of 3s+, the common default.
# Hard: cut aggressively -- shorter silences and quieter thresholds both count,
# with minimal padding, for a tightly-paced edit.
INTENSITY_PRESETS = {
    Intensity.SOFT: IntensitySettings(
        label="ソフト（控えめ）",
        silence_threshold_db=-35.0,
        min_silence_duration=6.0,
        padding=0.15,
        min_keep_duration=0.2,
    ),
    Intensity.STANDARD: IntensitySettings(
        label="標準",
        silence_threshold_db=-35.0,
        min_silence_duration=3.0,
        padding=0.1,
        min_keep_duration=0.15,
    ),
    Intensity.HARD: IntensitySettings(
        label="ハード（強めに詰める）",
        silence_threshold_db=-30.0,
        min_silence_duration=1.0,
        padding=0.05,
        min_keep_duration=0.1,
    ),
}


def get_settings(intensity) -> IntensitySettings:
    """Accepts an ``Intensity`` member or its string value (e.g. "hard")."""

    if isinstance(intensity, Intensity):
        return INTENSITY_PRESETS[intensity]
    return INTENSITY_PRESETS[Intensity(intensity)]
