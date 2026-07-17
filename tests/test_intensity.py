import pytest

from silence_cut_app.intensity import INTENSITY_PRESETS, Intensity, get_settings


def test_get_settings_accepts_enum_member():
    settings = get_settings(Intensity.SOFT)
    assert settings is INTENSITY_PRESETS[Intensity.SOFT]


def test_get_settings_accepts_string_value():
    settings = get_settings("hard")
    assert settings is INTENSITY_PRESETS[Intensity.HARD]


def test_get_settings_rejects_unknown_string():
    with pytest.raises(ValueError):
        get_settings("extreme")


def test_intensity_ordering_soft_to_hard():
    soft = INTENSITY_PRESETS[Intensity.SOFT]
    standard = INTENSITY_PRESETS[Intensity.STANDARD]
    hard = INTENSITY_PRESETS[Intensity.HARD]

    # soft requires the longest silence before cutting, hard the shortest.
    assert soft.min_silence_duration > standard.min_silence_duration > hard.min_silence_duration
    # hard leaves the least padding around a cut.
    assert soft.padding >= standard.padding >= hard.padding


def test_soft_standard_hard_match_requested_thresholds():
    assert INTENSITY_PRESETS[Intensity.SOFT].min_silence_duration == 6.0
    assert INTENSITY_PRESETS[Intensity.STANDARD].min_silence_duration == 3.0
