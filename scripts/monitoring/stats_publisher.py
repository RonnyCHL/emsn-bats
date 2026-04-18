"""EMSN Sonar Stats Publisher - publiceert aggregaten naar MQTT.

Leest vandaag's detecties uit de BatDetect2 SQLite DB en publiceert totals
naar `emsn2/sonar/stats` (retained). Wordt gebruikt door Home Assistant
sensoren en het live-dashboard voor snelle stat-lookups zonder DB queries.

Draait periodiek via timer.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from scripts.detection.mqtt_publisher import publish_health, publish_stats

logger = logging.getLogger("stats_publisher")

DB_PATH: Path = Path.home() / "emsn-sonar" / "data" / "bats.db"
BAVARIA_DB: Path = Path.home() / "emsn-sonar" / "data" / "batty_bavaria.db"


def _query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    """Helper: execute SELECT en return eerste scalar (int)."""
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row and row[0] is not None else 0)


def _gather_stats() -> dict:
    """Aggregeer BatDetect2 stats uit SQLite."""
    if not DB_PATH.exists():
        logger.warning("BatDetect2 DB nog niet aangemaakt: %s", DB_PATH)
        return {
            "today": 0, "total": 0, "last_hour": 0,
            "species_today": 0, "total_species": 0,
            "bavaria_today": 0,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    try:
        stats = {
            "today": _query_one(
                conn,
                "SELECT COUNT(*) FROM detections WHERE detection_time LIKE ?",
                (f"{today}%",),
            ),
            "total": _query_one(conn, "SELECT COUNT(*) FROM detections"),
            "last_hour": _query_one(
                conn,
                "SELECT COUNT(*) FROM detections "
                "WHERE detection_time >= datetime('now', '-1 hour', 'localtime')",
            ),
            "species_today": _query_one(
                conn,
                "SELECT COUNT(DISTINCT species) FROM detections "
                "WHERE detection_time LIKE ?",
                (f"{today}%",),
            ),
            "total_species": _query_one(
                conn, "SELECT COUNT(DISTINCT species) FROM detections"
            ),
        }
    finally:
        conn.close()

    # Bavaria stats als die DB bestaat
    if BAVARIA_DB.exists():
        bav = sqlite3.connect(f"file:{BAVARIA_DB}?mode=ro", uri=True, timeout=30)
        try:
            stats["bavaria_today"] = _query_one(
                bav,
                "SELECT COUNT(*) FROM detections WHERE recorded_at LIKE ?",
                (f"{today}%",),
            )
        finally:
            bav.close()
    else:
        stats["bavaria_today"] = 0

    stats["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return stats


def main() -> int:
    """Entry point voor systemd timer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    stats = _gather_stats()
    logger.info(
        "Stats: today=%d last_hour=%d species_today=%d bavaria_today=%d total=%d",
        stats["today"], stats["last_hour"], stats["species_today"],
        stats["bavaria_today"], stats["total"],
    )

    ok_stats = publish_stats(stats)
    # Health is simpelweg: we kunnen de DB lezen en MQTT bereiken
    ok_health = publish_health({
        "online": True,
        "last_update": stats["updated_at"],
    })

    if not (ok_stats and ok_health):
        logger.warning("Niet alle MQTT publishes slaagden (stats=%s health=%s)",
                       ok_stats, ok_health)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
