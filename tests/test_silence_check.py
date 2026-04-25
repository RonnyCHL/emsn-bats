"""Tests voor scripts.monitoring.detection_silence_check.

Verifieert de pure ``evaluate()`` flow: dag/nacht venster, recording-
disabled bypass, en het echte alert-pad.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.monitoring import detection_silence_check as dsc


def _insert_detection(db: Path, when: datetime) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO detections (detection_time, species, confidence) VALUES (?, ?, ?)",
            (when.strftime("%Y-%m-%d %H:%M:%S"), "Test bat", 0.7),
        )
        conn.commit()
    finally:
        conn.close()


def test_status_daytime_when_not_active(monkeypatch, empty_bats_db: Path) -> None:
    monkeypatch.setattr(dsc, "DB_PATH", empty_bats_db)
    monkeypatch.setattr(dsc, "_is_active_detection_window", lambda now: False)

    payload = dsc.evaluate()
    assert payload["status"] == dsc._STATUS_DAYTIME
    assert payload["detections_last_2h"] == 0


def test_status_disabled_when_recording_off(monkeypatch, empty_bats_db: Path) -> None:
    # Forceer "actief venster"
    monkeypatch.setattr(dsc, "DB_PATH", empty_bats_db)
    monkeypatch.setattr(dsc, "_is_active_detection_window", lambda now: True)
    # Schakel recording uit in de settings
    conn = sqlite3.connect(empty_bats_db)
    try:
        conn.execute(
            "UPDATE settings SET value = 'false' WHERE key = 'recording.enabled'"
        )
        conn.commit()
    finally:
        conn.close()

    payload = dsc.evaluate()
    assert payload["status"] == dsc._STATUS_DISABLED


def test_status_silent_when_no_recent_detections(
    monkeypatch, empty_bats_db: Path
) -> None:
    monkeypatch.setattr(dsc, "DB_PATH", empty_bats_db)
    monkeypatch.setattr(dsc, "_is_active_detection_window", lambda now: True)
    # Geen rijen ingevoegd

    payload = dsc.evaluate()
    assert payload["status"] == dsc._STATUS_SILENT
    assert payload["detections_last_2h"] == 0


def test_status_ok_with_recent_detection(
    monkeypatch, empty_bats_db: Path
) -> None:
    monkeypatch.setattr(dsc, "DB_PATH", empty_bats_db)
    monkeypatch.setattr(dsc, "_is_active_detection_window", lambda now: True)
    _insert_detection(empty_bats_db, datetime.now() - timedelta(minutes=10))

    payload = dsc.evaluate()
    assert payload["status"] == dsc._STATUS_OK
    assert payload["detections_last_2h"] == 1


def test_old_detections_outside_lookback_dont_count(
    monkeypatch, empty_bats_db: Path
) -> None:
    monkeypatch.setattr(dsc, "DB_PATH", empty_bats_db)
    monkeypatch.setattr(dsc, "_is_active_detection_window", lambda now: True)
    # 3 uur geleden = buiten lookback van 2u
    _insert_detection(empty_bats_db, datetime.now() - timedelta(hours=3))

    payload = dsc.evaluate()
    assert payload["status"] == dsc._STATUS_SILENT
    assert payload["detections_last_2h"] == 0
