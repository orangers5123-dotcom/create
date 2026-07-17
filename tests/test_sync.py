import numpy as np
import pytest

from silence_cut_app.sync import find_offset_seconds

SAMPLE_RATE = 16000


def _noise(n, seed=0):
    return np.random.default_rng(seed).standard_normal(n)


def test_offset_positive_when_cam2_has_more_lead_in():
    # cam2's own file contains extra lead-in before the content shared with
    # cam1 -- i.e. cam2 started rolling earlier.
    cam1 = _noise(20000)
    cam2 = np.zeros(30000)
    lead_in_samples = 5000
    cam2[lead_in_samples : lead_in_samples + len(cam1)] = cam1

    offset = find_offset_seconds(cam1, cam2, SAMPLE_RATE)
    assert offset == pytest.approx(lead_in_samples / SAMPLE_RATE, abs=1e-6)


def test_offset_negative_when_cam2_started_later():
    # cam2 is missing the first part of the shared content -- it started
    # rolling after cam1 already had.
    cam1 = _noise(20000)
    skipped_samples = 3000
    cam2 = cam1[skipped_samples:]

    offset = find_offset_seconds(cam1, cam2, SAMPLE_RATE)
    assert offset == pytest.approx(-skipped_samples / SAMPLE_RATE, abs=1e-6)


def test_offset_zero_for_identical_signals():
    cam1 = _noise(15000)
    offset = find_offset_seconds(cam1, cam1.copy(), SAMPLE_RATE)
    assert offset == pytest.approx(0.0, abs=1e-6)


def test_max_offset_sec_constrains_search_window():
    cam1 = _noise(20000)
    cam2 = np.zeros(30000)
    lead_in_samples = 5000
    cam2[lead_in_samples : lead_in_samples + len(cam1)] = cam1

    # A search window narrower than the true offset can't find the real
    # peak -- it should still return something within the allowed window
    # rather than the true (excluded) answer.
    narrow_offset = find_offset_seconds(cam1, cam2, SAMPLE_RATE, max_offset_sec=0.1)
    assert abs(narrow_offset) <= 0.1 + 1e-6


def test_empty_signal_raises():
    with pytest.raises(ValueError):
        find_offset_seconds(np.array([]), _noise(100), SAMPLE_RATE)
