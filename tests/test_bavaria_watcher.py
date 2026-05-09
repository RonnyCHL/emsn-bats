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
