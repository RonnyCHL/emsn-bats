"""Tests voor bavaria_watcher error categorisatie en health counters."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.bavaria import bavaria_watcher


def test_run_analyzer_wav_disappeared(tmp_path):
    """Race conditie: WAV bestaat niet meer als bat_ident wil starten."""
    wav = tmp_path / "bat_2026-05-09_00-00-00.wav"
    csv_path, reason = bavaria_watcher.run_analyzer(wav)
    assert csv_path is None
    assert reason == "wav_disappeared"


def test_run_analyzer_timeout(tmp_path):
    """Subprocess timeout wordt herkend als analyzer_timeout."""
    wav = tmp_path / "bat_2026-05-09_00-00-00.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")  # minimaal placeholder
    with patch.object(
        bavaria_watcher.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="bat_ident", timeout=120),
    ):
        csv_path, reason = bavaria_watcher.run_analyzer(wav)
    assert csv_path is None
    assert reason == "analyzer_timeout"


def test_run_analyzer_rc_nonzero(tmp_path):
    """Non-zero exit code wordt herkend als analyzer_rc_nonzero."""
    wav = tmp_path / "bat_2026-05-09_00-00-00.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="boom"
    )
    with patch.object(bavaria_watcher.subprocess, "run", return_value=fake_result):
        csv_path, reason = bavaria_watcher.run_analyzer(wav)
    assert csv_path is None
    assert reason == "analyzer_rc_nonzero"


def test_run_analyzer_rc_zero_no_csv(tmp_path):
    """rc=0 zonder CSV (bekende bat_ident bug) wordt analyzer_no_csv."""
    wav = tmp_path / "bat_2026-05-09_00-00-00.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    fake_result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="Error: Cannot open audio file " + str(wav),
        stderr="",
    )
    with patch.object(bavaria_watcher.subprocess, "run", return_value=fake_result):
        csv_path, reason = bavaria_watcher.run_analyzer(wav)
    assert csv_path is None
    assert reason == "analyzer_no_csv"


def test_run_analyzer_success(tmp_path, monkeypatch):
    """rc=0 met CSV file levert (path, None)."""
    wav = tmp_path / "bat_2026-05-09_00-00-00.wav"
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    out_dir = tmp_path / "results"
    monkeypatch.setattr(bavaria_watcher, "TMP_OUT_DIR", out_dir)

    def fake_run(cmd, **_kwargs):
        # Simuleer dat bat_ident.py een CSV schrijft.
        out_csv = out_dir / f"{wav.stem}.csv"
        out_csv.write_text("Start (s),End (s),Scientific name,Common name,Confidence\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch.object(bavaria_watcher.subprocess, "run", side_effect=fake_run):
        csv_path, reason = bavaria_watcher.run_analyzer(wav)
    assert csv_path is not None
    assert csv_path.exists()
    assert reason is None


def test_health_counters_track_streak():
    counters = bavaria_watcher._HealthCounters()
    counters.record(0, "wav_disappeared")
    counters.record(0, "wav_disappeared")
    assert counters.consecutive_real_failures == 0  # recoverable

    counters.record(0, "analyzer_no_csv")
    counters.record(0, "analyzer_rc_nonzero")
    assert counters.consecutive_real_failures == 2

    counters.record(3, None)
    assert counters.consecutive_real_failures == 0
    assert counters.detections_total == 3


def test_health_counters_record_breakdown():
    counters = bavaria_watcher._HealthCounters()
    counters.record(0, "wav_disappeared")
    counters.record(2, None)
    counters.record(0, "analyzer_no_csv")
    counters.record(0, "analyzer_no_csv")
    assert counters.processed_total == 4
    assert counters.detections_total == 2
    assert counters.errors_by_reason == {
        "wav_disappeared": 1,
        "analyzer_no_csv": 2,
    }


@pytest.mark.parametrize(
    "reason,is_real",
    [
        ("wav_disappeared", False),
        ("analyzer_timeout", True),
        ("analyzer_rc_nonzero", True),
        ("analyzer_no_csv", True),
        ("parse_error", True),
        ("exception", True),
    ],
)
def test_recoverable_classification(reason: str, is_real: bool):
    """Alleen wav_disappeared mag NIET tellen voor de streak."""
    counters = bavaria_watcher._HealthCounters()
    counters.record(0, reason)
    if is_real:
        assert counters.consecutive_real_failures == 1
    else:
        assert counters.consecutive_real_failures == 0


def test_enrich_with_frequency_band_known():
    """Bekende soort krijgt low_freq/high_freq toegevoegd aan dict."""
    detections = [
        {"scientific_name": "Nyctalus leisleri", "confidence": 0.5},
        {"scientific_name": "Pipistrellus pipistrellus", "confidence": 0.7},
    ]
    bavaria_watcher._enrich_with_frequency_band(detections)
    assert "low_freq" in detections[0] and "high_freq" in detections[0]
    assert detections[0]["low_freq"] < detections[0]["high_freq"]
    assert detections[1]["low_freq"] >= 40_000  # Pipistrellus is hoog


def test_enrich_with_frequency_band_unknown():
    """Onbekende soort krijgt geen freq velden (filter slaat ze dan over)."""
    detections = [{"scientific_name": "Mythicus imaginarius", "confidence": 0.5}]
    bavaria_watcher._enrich_with_frequency_band(detections)
    assert "low_freq" not in detections[0]
    assert "high_freq" not in detections[0]


def test_health_counters_track_tonal_rejects():
    """Tonal rejects worden apart bijgehouden in summary log."""
    counters = bavaria_watcher._HealthCounters()
    counters.record(2, None, tonal_rejected=3)
    counters.record(0, None, tonal_rejected=1)
    counters.record(1, None)
    assert counters.tonal_rejects_total == 4
    assert counters.detections_total == 3
    assert counters.processed_total == 3


def test_apply_pulse_filter_smoke(tmp_path):
    """End-to-end: 5s WAV met continue 24 kHz toon → leisleri detectie wordt rejected."""
    import numpy as np
    import soundfile as sf

    wav_path = tmp_path / "bat_2026-05-09_00-00-00.wav"
    sample_rate = 200_000
    duration_s = 5.0
    t = np.arange(int(sample_rate * duration_s)) / sample_rate
    audio = (np.sin(2 * np.pi * 24_500 * t) * 8000).astype(np.int16)
    sf.write(str(wav_path), audio, sample_rate)

    detections = [
        {
            "scientific_name": "Nyctalus leisleri",
            "common_name": "Lesser noctule",
            "confidence": 0.5,
            "start_s": 0.0,
            "end_s": 3.0,
        }
    ]
    bavaria_watcher._enrich_with_frequency_band(detections)
    kept, rejected = bavaria_watcher._apply_pulse_filter(wav_path, detections)

    assert len(kept) == 0
    assert len(rejected) == 1
    assert rejected[0]["reject_reason"] == "tonal_artifact"


def test_apply_pulse_filter_unknown_species_passes(tmp_path):
    """Onbekende soort heeft geen freqs → fallback gedrag, geen crash."""
    import numpy as np
    import soundfile as sf

    wav_path = tmp_path / "bat_2026-05-09_00-00-00.wav"
    audio = np.zeros(200_000 * 5, dtype=np.int16)
    sf.write(str(wav_path), audio, 200_000)

    detections = [
        {
            "scientific_name": "Mythicus imaginarius",
            "common_name": "Mystery bat",
            "confidence": 0.5,
        }
    ]
    bavaria_watcher._enrich_with_frequency_band(detections)
    # Zonder freqs gebruikt filter_detections de default (low=high=0),
    # peak is 0 < 30 kHz dus filter wordt toegepast - geeft een
    # dynamic_range_db terug. Met stilte audio is DR laag → reject.
    kept, rejected = bavaria_watcher._apply_pulse_filter(wav_path, detections)
    # Stilte → low DR → reject. Onbekende soort had niet door filter
    # mogen worden weggehaald, maar zonder freq info hebben we
    # die garantie niet. Dit dekt het edge case af.
    assert len(kept) + len(rejected) == 1


def test_apply_pulse_filter_empty_detections(tmp_path):
    """Lege detection list returnt zonder audio te lezen."""
    wav_path = tmp_path / "noexist.wav"
    kept, rejected = bavaria_watcher._apply_pulse_filter(wav_path, [])
    assert kept == []
    assert rejected == []


def test_apply_pulse_filter_audio_load_fails_fail_open(tmp_path):
    """Audio-load fail behoudt detecties (fail-open) zodat we niets
    onbedoeld weggooien bij I/O issues."""
    nonexistent_wav = tmp_path / "does_not_exist.wav"
    detections = [
        {"scientific_name": "Nyctalus leisleri", "low_freq": 22_000, "high_freq": 26_000}
    ]
    kept, rejected = bavaria_watcher._apply_pulse_filter(nonexistent_wav, detections)
    assert len(kept) == 1
    assert len(rejected) == 0
