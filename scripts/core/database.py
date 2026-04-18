"""Lokale SQLite database voor BatDetect detecties."""

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path.home() / "emsn-sonar" / "data" / "bats.db"

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Thread-safe SQLite connectie."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def init_db():
    """Maak tabellen aan als ze niet bestaan."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS detections (
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

        CREATE INDEX IF NOT EXISTS idx_detections_time
            ON detections (detection_time);
        CREATE INDEX IF NOT EXISTS idx_detections_species
            ON detections (species);
        CREATE INDEX IF NOT EXISTS idx_detections_synced
            ON detections (synced_to_pg);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT NOT NULL,
            species TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            max_confidence REAL,
            first_detection TEXT,
            last_detection TEXT,
            PRIMARY KEY (date, species)
        );
    """)
    conn.commit()


def get_setting(key: str, default: str = "") -> str:
    """Haal een instelling op."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    """Sla een instelling op."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO settings (key, value, updated_at)
           VALUES (?, ?, datetime('now', 'localtime'))
           ON CONFLICT(key) DO UPDATE SET
               value = excluded.value,
               updated_at = excluded.updated_at""",
        (key, value),
    )
    conn.commit()


def insert_detection(detection: dict) -> int:
    """Voeg een detectie toe, return ID."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO detections
           (detection_time, species, species_dutch, confidence, det_prob,
            frequency_low, frequency_high, frequency_peak, duration_ms,
            file_name, audio_path, spectrogram_path, station)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            detection["detection_time"],
            detection.get("species"),
            detection.get("species_dutch"),
            detection.get("confidence"),
            detection.get("det_prob"),
            detection.get("frequency_low"),
            detection.get("frequency_high"),
            detection.get("frequency_peak"),
            detection.get("duration_ms"),
            detection.get("file_name"),
            detection.get("audio_path"),
            detection.get("spectrogram_path"),
            detection.get("station", "emsn-sonar"),
        ),
    )
    conn.commit()

    # Update daily_stats
    date = detection["detection_time"][:10]
    species = detection.get("species", "Unknown")
    confidence = detection.get("confidence", 0)
    det_time = detection["detection_time"]

    conn.execute(
        """INSERT INTO daily_stats (date, species, count, max_confidence,
                                    first_detection, last_detection)
           VALUES (?, ?, 1, ?, ?, ?)
           ON CONFLICT(date, species) DO UPDATE SET
               count = count + 1,
               max_confidence = MAX(max_confidence, excluded.max_confidence),
               last_detection = excluded.last_detection""",
        (date, species, confidence, det_time, det_time),
    )
    conn.commit()
    return cursor.lastrowid


def get_recent_detections(limit: int = 20) -> list[dict]:
    """Laatste detecties."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM detections
           ORDER BY detection_time DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_today_stats() -> dict:
    """Statistieken voor vandaag."""
    conn = get_connection()
    today = conn.execute(
        "SELECT date('now', 'localtime')"
    ).fetchone()[0]

    total_today = conn.execute(
        "SELECT COUNT(*) FROM detections WHERE detection_time LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]

    species_today = conn.execute(
        "SELECT COUNT(DISTINCT species) FROM detections WHERE detection_time LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]

    total_all = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]

    total_species = conn.execute(
        "SELECT COUNT(DISTINCT species) FROM detections"
    ).fetchone()[0]

    last_hour = conn.execute(
        """SELECT COUNT(*) FROM detections
           WHERE detection_time >= datetime('now', 'localtime', '-1 hour')"""
    ).fetchone()[0]

    return {
        "today": total_today,
        "species_today": species_today,
        "total": total_all,
        "total_species": total_species,
        "last_hour": last_hour,
    }


def get_today_species() -> list[dict]:
    """Soorten van vandaag met counts."""
    conn = get_connection()
    today = conn.execute(
        "SELECT date('now', 'localtime')"
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT species, species_dutch, COUNT(*) as count,
                  MAX(confidence) as max_confidence,
                  MIN(detection_time) as first_detection,
                  MAX(detection_time) as last_detection
           FROM detections
           WHERE detection_time LIKE ?
           GROUP BY species
           ORDER BY count DESC""",
        (f"{today}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_hourly_counts(date: str | None = None) -> list[dict]:
    """Detecties per uur voor een datum."""
    conn = get_connection()
    if date is None:
        date = conn.execute(
            "SELECT date('now', 'localtime')"
        ).fetchone()[0]
    rows = conn.execute(
        """SELECT CAST(strftime('%H', detection_time) AS INTEGER) as hour,
                  COUNT(*) as count
           FROM detections
           WHERE detection_time LIKE ?
           GROUP BY hour
           ORDER BY hour""",
        (f"{date}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_species_history(species: str, days: int = 30) -> list[dict]:
    """Detectie geschiedenis voor een soort."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date, count, max_confidence
           FROM daily_stats
           WHERE species = ?
             AND date >= date('now', 'localtime', ?)
           ORDER BY date""",
        (species, f"-{days} days"),
    ).fetchall()
    return [dict(r) for r in rows]
