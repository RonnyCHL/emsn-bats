"""Tests voor pulse_structure_filter."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.detection.pulse_structure_filter import (
    DEFAULT_MIN_DYNAMIC_RANGE_DB,
    compute_dynamic_range_db,
    filter_detections,
)

SAMPLE_RATE = 200_000
DURATION_S = 5.0
N_SAMPLES = int(SAMPLE_RATE * DURATION_S)


def _continuous_tone(freq: float, sample_rate: int, duration_s: float) -> np.ndarray:
    """Genereer een continue zuivere sinus over de hele duur."""
    t = np.arange(int(sample_rate * duration_s)) / sample_rate
    return (np.sin(2 * np.pi * freq * t) * 8000).astype(np.int16)


def _pulsed_fm_call(
    sample_rate: int,
    duration_s: float,
    n_pulses: int,
    pulse_ms: float,
    f_start: float,
    f_end: float,
) -> np.ndarray:
    """Genereer ``n_pulses`` korte FM down-sweep pulsen op gelijkmatige tussenpozen."""
    n_total = int(sample_rate * duration_s)
    audio = np.zeros(n_total, dtype=np.float64)
    pulse_samples = int(sample_rate * pulse_ms / 1000.0)
    spacing = n_total // (n_pulses + 1)

    pulse_t = np.arange(pulse_samples) / sample_rate
    instantaneous_phase = 2 * np.pi * (
        f_start * pulse_t
        + 0.5 * (f_end - f_start) / (pulse_ms / 1000.0) * pulse_t**2
    )
    pulse = np.sin(instantaneous_phase) * np.hanning(pulse_samples) * 16000

    for i in range(n_pulses):
        start = (i + 1) * spacing
        end = min(start + pulse_samples, n_total)
        audio[start:end] += pulse[: end - start]

    return audio.astype(np.int16)


def test_continuous_tone_has_low_dynamic_range():
    """Een 24 kHz continue toon moet <10 dB dynamic range geven."""
    audio = _continuous_tone(24_000, SAMPLE_RATE, DURATION_S)
    dr = compute_dynamic_range_db(audio, SAMPLE_RATE, 22_000, 26_000)
    assert dr < 10.0, f"verwacht <10 dB voor continue toon, kreeg {dr:.1f}"


def test_pulsed_fm_call_has_high_dynamic_range():
    """Korte FM-pulsen moeten >25 dB dynamic range geven."""
    audio = _pulsed_fm_call(
        SAMPLE_RATE, DURATION_S, n_pulses=6, pulse_ms=10, f_start=55_000, f_end=45_000
    )
    dr = compute_dynamic_range_db(audio, SAMPLE_RATE, 45_000, 55_000)
    assert dr > 25.0, f"verwacht >25 dB voor pulsen, kreeg {dr:.1f}"


def test_silence_returns_low_dynamic_range():
    """Witte ruis zonder signaal heeft beperkte dynamic range."""
    audio = (np.random.default_rng(42).normal(0, 50, N_SAMPLES)).astype(np.int16)
    dr = compute_dynamic_range_db(audio, SAMPLE_RATE, 22_000, 26_000)
    assert dr < 15.0


def test_filter_rejects_continuous_keeps_pulsed():
    """Volledig pad: filter moet tonale toon weigeren en pulsen behouden."""
    tonal = _continuous_tone(24_500, SAMPLE_RATE, DURATION_S)
    pulsed = _pulsed_fm_call(
        SAMPLE_RATE, DURATION_S, n_pulses=6, pulse_ms=8, f_start=52_000, f_end=46_000
    )
    audio = (
        (tonal.astype(np.int32) + pulsed.astype(np.int32))
        .clip(-32768, 32767)
        .astype(np.int16)
    )

    detections = [
        {"low_freq": 22_000, "high_freq": 26_000, "class": "Nyctalus leisleri"},
        {"low_freq": 46_000, "high_freq": 52_000, "class": "Pipistrellus pipistrellus"},
    ]

    kept, rejected = filter_detections(audio, SAMPLE_RATE, detections)

    assert len(kept) == 1
    assert len(rejected) == 1
    assert kept[0]["class"] == "Pipistrellus pipistrellus"
    assert rejected[0]["class"] == "Nyctalus leisleri"
    assert rejected[0]["reject_reason"] == "tonal_artifact"
    assert rejected[0]["dynamic_range_db"] < DEFAULT_MIN_DYNAMIC_RANGE_DB
    # Dwergvleermuis op 46-52 kHz valt boven cutoff: skip filter, dr=None
    assert kept[0]["dynamic_range_db"] is None


def test_empty_detections_returns_empty():
    """Geen detecties → geen kept, geen rejected, geen crash."""
    audio = np.zeros(N_SAMPLES, dtype=np.int16)
    kept, rejected = filter_detections(audio, SAMPLE_RATE, [])
    assert kept == []
    assert rejected == []


def test_short_audio_does_not_crash():
    """Audio korter dan één STFT-window mag niet crashen."""
    audio = np.zeros(100, dtype=np.int16)
    dr = compute_dynamic_range_db(audio, SAMPLE_RATE, 22_000, 26_000)
    assert dr == 0.0


def test_zero_band_is_widened_to_minimum():
    """Een nul-breedte band (low==high) moet veilig worden verbreed."""
    audio = _continuous_tone(24_000, SAMPLE_RATE, DURATION_S)
    dr = compute_dynamic_range_db(audio, SAMPLE_RATE, 24_000, 24_000)
    assert dr < 10.0


def test_high_freq_detection_skips_filter():
    """Detecties met peak >= 30 kHz worden niet gefilterd, ook niet bij stilte."""
    audio = np.zeros(N_SAMPLES, dtype=np.int16)
    detections = [
        {"low_freq": 46_000, "high_freq": 52_000, "class": "Pipistrellus pipistrellus"},
        {"low_freq": 36_000, "high_freq": 41_000, "class": "Pipistrellus nathusii"},
    ]
    kept, rejected = filter_detections(audio, SAMPLE_RATE, detections)
    assert len(kept) == 2
    assert len(rejected) == 0
    assert all(d["dynamic_range_db"] is None for d in kept)


def test_low_freq_continuous_tone_still_rejected():
    """Detecties in de problematische 18-30 kHz zone worden wel gefilterd."""
    audio = _continuous_tone(24_500, SAMPLE_RATE, DURATION_S)
    detections = [
        {"low_freq": 22_000, "high_freq": 26_000, "class": "Nyctalus leisleri"},
    ]
    kept, rejected = filter_detections(audio, SAMPLE_RATE, detections)
    assert len(kept) == 0
    assert len(rejected) == 1


def test_max_peak_freq_is_configurable():
    """Cutoff-grens moet via parameter aanpasbaar zijn."""
    audio = _continuous_tone(40_000, SAMPLE_RATE, DURATION_S)
    detections = [{"low_freq": 38_000, "high_freq": 42_000, "class": "test"}]

    kept_default, _ = filter_detections(audio, SAMPLE_RATE, detections.copy())
    assert len(kept_default) == 1

    kept_strict, rejected_strict = filter_detections(
        audio, SAMPLE_RATE, [dict(detections[0])], max_peak_freq_hz=50_000.0
    )
    assert len(kept_strict) == 0
    assert len(rejected_strict) == 1


@pytest.mark.parametrize("threshold_db", [10.0, 15.0, 20.0])
def test_threshold_is_respected(threshold_db: float):
    """Strenger threshold moet meer detecties weigeren."""
    audio = (
        _continuous_tone(24_000, SAMPLE_RATE, DURATION_S).astype(np.int32)
        + _pulsed_fm_call(
            SAMPLE_RATE, DURATION_S, n_pulses=4, pulse_ms=10,
            f_start=52_000, f_end=46_000,
        ).astype(np.int32)
    ).clip(-32768, 32767).astype(np.int16)

    detections = [
        {"low_freq": 22_000, "high_freq": 26_000, "class": "tonal"},
        {"low_freq": 46_000, "high_freq": 52_000, "class": "pulsed"},
    ]
    kept, rejected = filter_detections(
        audio, SAMPLE_RATE, detections, min_dynamic_range_db=threshold_db
    )
    pulsed_kept = any(d["class"] == "pulsed" for d in kept)
    tonal_rejected = any(d["class"] == "tonal" for d in rejected)
    assert pulsed_kept, "pulsen moeten altijd door drempel komen"
    assert tonal_rejected, "tonale moet altijd worden afgewezen"
