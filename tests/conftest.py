"""Pytest fixtures voor de emsn-sonar test suite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def empty_bats_db(tmp_path: Path) -> Path:
    """Maak een lege ``bats.db`` met het sonar schema in een tmp dir."""
    db = tmp_path / "bats.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detection_time TEXT NOT NULL,
                species TEXT,
                species_dutch TEXT,
                confidence REAL,
                det_prob REAL,
                frequency_low REAL,
                frequency_high REAL,
                frequency_peak REAL,
                duration_ms REAL,
                file_name TEXT,
                audio_path TEXT,
                spectrogram_path TEXT,
                station TEXT DEFAULT 'emsn-sonar',
                synced_to_pg INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX idx_detections_time ON detections (detection_time);

            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT INTO settings (key, value) VALUES
                ('recording.enabled', 'true'),
                ('recording.night_only', 'true'),
                ('recording.sample_rate', '200000');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db
