"""SQLite -> PostgreSQL sync voor vleermuisdetecties.

Synct ongesyncte detecties van de lokale SQLite database naar
de centrale PostgreSQL database op de NAS.
"""

import logging

import psycopg2

from scripts.core.database import get_connection as get_sqlite
from scripts.core.secrets import get_pg_config

logger = logging.getLogger("batdetect2_sync")


def get_pg_connection() -> psycopg2.extensions.connection:
    """Maak PostgreSQL connectie."""
    config = get_pg_config()
    return psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
        connect_timeout=10,
    )


def sync_detections() -> int:
    """Sync ongesyncte detecties naar PostgreSQL.

    Returns:
        Aantal gesyncte records.
    """
    sqlite_conn = get_sqlite()
    rows = sqlite_conn.execute(
        """SELECT id, detection_time, species, species_dutch, confidence,
                  det_prob, frequency_low, frequency_high, frequency_peak,
                  duration_ms, file_name, audio_path, spectrogram_path, station
           FROM detections
           WHERE synced_to_pg = 0
           ORDER BY id
           LIMIT 1000"""
    ).fetchall()

    if not rows:
        logger.info("Geen ongesyncte detecties")
        return 0

    logger.info("%d detecties te syncen", len(rows))

    try:
        pg_conn = get_pg_connection()
        pg_cur = pg_conn.cursor()

        synced_ids: list[int] = []
        for row in rows:
            try:
                pg_cur.execute(
                    """INSERT INTO bat_detections
                       (detection_timestamp, species, species_dutch, confidence,
                        det_prob, frequency_min, frequency_max, frequency_peak,
                        duration_ms, file_name, audio_path, spectrogram_path,
                        station, detector)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (detection_timestamp, station, species, detector)
                       DO NOTHING""",
                    (
                        row["detection_time"],
                        row["species"],
                        row["species_dutch"],
                        row["confidence"],
                        row["det_prob"],
                        row["frequency_low"],
                        row["frequency_high"],
                        row["frequency_peak"],
                        row["duration_ms"],
                        row["file_name"],
                        row["audio_path"],
                        row["spectrogram_path"],
                        row["station"],
                        "batdetect2",
                    ),
                )
                synced_ids.append(row["id"])
            except Exception:
                logger.exception("Fout bij sync detectie #%d", row["id"])

        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()

        # Markeer als gesynct in SQLite
        if synced_ids:
            placeholders = ",".join("?" * len(synced_ids))
            sqlite_conn.execute(
                f"UPDATE detections SET synced_to_pg = 1 WHERE id IN ({placeholders})",
                synced_ids,
            )
            sqlite_conn.commit()

        logger.info("Sync voltooid: %d detecties", len(synced_ids))
        return len(synced_ids)

    except psycopg2.OperationalError:
        logger.exception("PostgreSQL niet bereikbaar")
        return 0


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    count = sync_detections()
    logger.info("Totaal gesynct: %d", count)


if __name__ == "__main__":
    main()
