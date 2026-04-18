"""BattyBirdNET-Bavaria SQLite → PostgreSQL sync.

Synchroniseert vleermuis detecties uit de Bavaria-model SQLite DB
(geschreven door bavaria_watcher.py) naar de centrale PostgreSQL bat_detections
tabel op de NAS, met detector='bavaria' als marker.

Gebruikt ON CONFLICT DO NOTHING op (detection_timestamp, station, species,
detector) zodat de sync idempotent is en meerdere runs veilig zijn.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.core.config import get_config
from scripts.core.secrets import get_pg_config
from scripts.core.species import get_dutch_name

logger = logging.getLogger("bavaria_sync")

DB_PATH: Path = Path.home() / "emsn-sonar" / "data" / "batty_bavaria.db"
BATCH_SIZE: int = 1000
DETECTOR: str = "bavaria"


def _get_sqlite_connection() -> sqlite3.Connection:
    """Open Bavaria SQLite database read-write."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _get_pg_connection() -> psycopg2.extensions.connection:
    """Open PostgreSQL connectie met secrets uit .secrets."""
    config = get_pg_config()
    return psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
        connect_timeout=10,
    )


def _compute_detection_timestamp(recorded_at: str, start_s: float) -> datetime:
    """Bereken exact detectie-tijdstip: opname start + offset binnen WAV."""
    base = datetime.fromisoformat(recorded_at)
    return base + timedelta(seconds=start_s)


def _to_insert_params(row: sqlite3.Row, station: str) -> tuple:
    """Map een Bavaria detectie naar PostgreSQL bat_detections parameters."""
    wav_path = row["wav_path"]
    detection_ts = _compute_detection_timestamp(row["recorded_at"], row["start_s"])
    duration_ms = (row["end_s"] - row["start_s"]) * 1000.0
    dutch_name = (row["common_name"] or "").strip() or get_dutch_name(
        row["scientific_name"]
    )
    return (
        detection_ts,
        row["scientific_name"],
        dutch_name,
        float(row["confidence"]),
        None,  # det_prob - Bavaria model levert geen aparte detectie-kans
        None,  # frequency_min - niet beschikbaar in Bavaria output
        None,  # frequency_max
        None,  # frequency_peak
        duration_ms,
        Path(wav_path).name,  # file_name
        wav_path,  # audio_path
        # spectrogram_path uit sqlite row (None als watcher nog geen PNG had)
        (row["spectrogram_path"] if "spectrogram_path" in row.keys() else None),
        station,
        DETECTOR,
    )


def sync_detections() -> int:
    """Sync ongesyncte Bavaria detecties naar PostgreSQL.

    Returns:
        Aantal records dat als gesynct is gemarkeerd in SQLite.
        (Werkelijk nieuwe inserts kunnen lager zijn door ON CONFLICT.)
    """
    if not DB_PATH.exists():
        logger.info("Bavaria DB nog niet aangemaakt op %s - niets te doen", DB_PATH)
        return 0

    station = get_config("station.name") or "emsn-sonar"

    sqlite_conn = _get_sqlite_connection()
    try:
        rows = sqlite_conn.execute(
            """SELECT id, wav_path, recorded_at, start_s, end_s,
                      scientific_name, common_name, confidence,
                      spectrogram_path
               FROM detections
               WHERE synced_to_pg = 0
               ORDER BY id
               LIMIT ?""",
            (BATCH_SIZE,),
        ).fetchall()

        if not rows:
            logger.info("Geen ongesyncte Bavaria detecties")
            return 0

        logger.info("%d Bavaria detecties te syncen", len(rows))

        try:
            pg_conn = _get_pg_connection()
        except psycopg2.OperationalError:
            logger.exception("PostgreSQL niet bereikbaar - sync overgeslagen")
            return 0

        synced_ids: list[int] = []
        try:
            with pg_conn:
                with pg_conn.cursor() as pg_cur:
                    for row in rows:
                        try:
                            pg_cur.execute(
                                """INSERT INTO bat_detections
                                   (detection_timestamp, species, species_dutch,
                                    confidence, det_prob,
                                    frequency_min, frequency_max, frequency_peak,
                                    duration_ms, file_name, audio_path,
                                    spectrogram_path, station, detector)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                           %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT
                                       (detection_timestamp, station, species, detector)
                                   DO NOTHING""",
                                _to_insert_params(row, station),
                            )
                            synced_ids.append(row["id"])
                        except Exception:
                            logger.exception(
                                "Fout bij sync Bavaria detectie #%d", row["id"]
                            )
        finally:
            pg_conn.close()

        if synced_ids:
            placeholders = ",".join("?" * len(synced_ids))
            sqlite_conn.execute(
                f"UPDATE detections SET synced_to_pg = 1 WHERE id IN ({placeholders})",
                synced_ids,
            )
            sqlite_conn.commit()

        logger.info(
            "Bavaria sync voltooid: %d records gemarkeerd als gesynct", len(synced_ids)
        )
        return len(synced_ids)
    finally:
        sqlite_conn.close()


def main() -> int:
    """Entry point voor systemd service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    count = sync_detections()
    logger.info("Totaal gesynct: %d", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
