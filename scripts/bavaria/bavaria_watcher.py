#!/usr/bin/env python3
"""BattyBirdNET watcher voor emsn-sonar Pi.

Watcht ~/emsn-sonar/recordings/ voor nieuwe WAV bestanden, draait
bat_ident.py (Bavaria model) en slaat detecties op in een SQLite DB
naast die van BatDetect2. Geeft een onafhankelijk tweede oordeel
op exact dezelfde audio die emsn-sonar opneemt.
"""

from __future__ import annotations

import csv
import logging
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Vaste paden - dit script draait altijd op de Bats Pi
HOME = Path.home()
RECORDINGS_DIR = HOME / "emsn-sonar" / "recordings"
ANALYZER_DIR = HOME / "BattyBirdNET-Analyzer"
ANALYZER_VENV_PY = ANALYZER_DIR / "venv" / "bin" / "python3"
ANALYZER_SCRIPT = ANALYZER_DIR / "bat_ident.py"
DB_PATH = HOME / "emsn-sonar" / "data" / "batty_bavaria.db"
TMP_OUT_DIR = Path("/tmp/batty_results")

POLL_INTERVAL_SEC = 30
MIN_CONFIDENCE = 0.5
AREA = "Bavaria"
THREADS = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sonar-bavaria")

_running = True


def _sigterm(_signum, _frame):
    global _running
    log.info("SIGTERM ontvangen, stoppen na huidige iteratie")
    _running = False


signal.signal(signal.SIGTERM, _sigterm)
signal.signal(signal.SIGINT, _sigterm)


def init_db() -> sqlite3.Connection:
    """Maak SQLite DB en tabellen aan als ze nog niet bestaan."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_files (
            wav_path TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL,
            num_detections INTEGER NOT NULL DEFAULT 0,
            error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wav_path TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            scientific_name TEXT NOT NULL,
            common_name TEXT,
            confidence REAL NOT NULL,
            model_area TEXT NOT NULL,
            inserted_at TEXT NOT NULL,
            synced_to_pg INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # Migreer bestaande DBs zonder synced_to_pg kolom (idempotent)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(detections)").fetchall()]
    if "synced_to_pg" not in cols:
        conn.execute(
            "ALTER TABLE detections ADD COLUMN synced_to_pg INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_detections_recorded ON detections(recorded_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_detections_species ON detections(scientific_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_detections_synced ON detections(synced_to_pg)"
    )
    conn.commit()
    return conn


def parse_recorded_at(wav_path: Path) -> str:
    """Haal opname tijdstip uit bestandsnaam: bat_YYYY-MM-DD_HH-MM-SS.wav."""
    stem = wav_path.stem  # bat_2026-04-11_00-01-02
    try:
        _, date_part, time_part = stem.split("_")
        dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H-%M-%S")
        return dt.isoformat(timespec="seconds")
    except (ValueError, IndexError):
        # Fallback op file mtime als de naam niet matcht
        return datetime.fromtimestamp(wav_path.stat().st_mtime).isoformat(
            timespec="seconds"
        )


def find_unprocessed(conn: sqlite3.Connection) -> list[Path]:
    """Vind alle WAV files die nog niet verwerkt zijn."""
    if not RECORDINGS_DIR.exists():
        return []
    all_wavs = sorted(RECORDINGS_DIR.glob("*/bat_*.wav"))
    if not all_wavs:
        return []
    cur = conn.execute("SELECT wav_path FROM processed_files")
    done = {row[0] for row in cur.fetchall()}
    return [p for p in all_wavs if str(p) not in done]


def run_analyzer(wav_path: Path) -> Path | None:
    """Roep bat_ident.py aan, geeft pad naar output CSV."""
    TMP_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = TMP_OUT_DIR / f"{wav_path.stem}.csv"
    if out_csv.exists():
        out_csv.unlink()
    cmd = [
        str(ANALYZER_VENV_PY),
        str(ANALYZER_SCRIPT),
        "--i", str(wav_path),
        "--o", str(out_csv),
        "--area", AREA,
        "--kHz", "256",
        "--min_conf", str(MIN_CONFIDENCE),
        "--rtype", "csv",
        "--threads", str(THREADS),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ANALYZER_DIR),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("Timeout op %s", wav_path.name)
        return None
    if result.returncode != 0:
        log.warning(
            "bat_ident faalde rc=%d op %s: %s",
            result.returncode,
            wav_path.name,
            result.stderr.strip()[:300],
        )
        return None
    return out_csv if out_csv.exists() else None


def parse_csv(csv_path: Path) -> list[dict]:
    """Parse de CSV output van bat_ident.py."""
    detections = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                conf = float(row.get("Confidence", 0))
                if conf < MIN_CONFIDENCE:
                    continue
                detections.append({
                    "start_s": float(row.get("Start (s)", 0)),
                    "end_s": float(row.get("End (s)", 0)),
                    "scientific_name": row.get("Scientific name", "").strip(),
                    "common_name": row.get("Common name", "").strip(),
                    "confidence": conf,
                })
            except (ValueError, KeyError):
                continue
    return detections


def store_results(
    conn: sqlite3.Connection,
    wav_path: Path,
    detections: list[dict],
    error: str | None = None,
) -> None:
    """Schrijf detecties en processed marker naar de DB."""
    recorded_at = parse_recorded_at(wav_path)
    now = datetime.now().isoformat(timespec="seconds")
    with conn:
        for det in detections:
            conn.execute(
                """
                INSERT INTO detections
                    (wav_path, recorded_at, start_s, end_s, scientific_name,
                     common_name, confidence, model_area, inserted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(wav_path),
                    recorded_at,
                    det["start_s"],
                    det["end_s"],
                    det["scientific_name"],
                    det["common_name"],
                    det["confidence"],
                    AREA,
                    now,
                ),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO processed_files
                (wav_path, processed_at, num_detections, error)
            VALUES (?, ?, ?, ?)
            """,
            (str(wav_path), now, len(detections), error),
        )


def process_one(conn: sqlite3.Connection, wav_path: Path) -> int:
    """Verwerk één WAV. Return aantal detecties."""
    csv_path = run_analyzer(wav_path)
    if csv_path is None:
        store_results(conn, wav_path, [], error="analyzer_failed")
        return 0
    detections = parse_csv(csv_path)
    store_results(conn, wav_path, detections)
    try:
        csv_path.unlink()
    except OSError:
        pass
    if detections:
        names = ", ".join(
            f"{d['common_name']} ({d['confidence']:.2f})" for d in detections[:3]
        )
        log.info("%s -> %d detecties: %s", wav_path.name, len(detections), names)
    return len(detections)


def main() -> int:
    if not ANALYZER_SCRIPT.exists():
        log.error("bat_ident.py niet gevonden op %s", ANALYZER_SCRIPT)
        return 1
    if not ANALYZER_VENV_PY.exists():
        log.error("Analyzer venv python niet gevonden op %s", ANALYZER_VENV_PY)
        return 1
    conn = init_db()
    log.info("BattyBirdNET watcher gestart, DB=%s", DB_PATH)
    log.info("Polling %s elke %ds (model=%s, min_conf=%.2f)",
             RECORDINGS_DIR, POLL_INTERVAL_SEC, AREA, MIN_CONFIDENCE)
    iterations_idle = 0
    while _running:
        try:
            todo = find_unprocessed(conn)
            if not todo:
                iterations_idle += 1
                if iterations_idle == 1:
                    log.info("Geen nieuwe WAVs, wachten...")
                _sleep_interruptible(POLL_INTERVAL_SEC)
                continue
            iterations_idle = 0
            log.info("%d nieuwe WAVs te verwerken", len(todo))
            for wav in todo:
                if not _running:
                    break
                try:
                    process_one(conn, wav)
                except Exception:
                    log.exception("Fout bij verwerken %s", wav)
                    store_results(conn, wav, [], error="exception")
        except Exception:
            log.exception("Onverwachte fout in main loop")
            _sleep_interruptible(POLL_INTERVAL_SEC)
    log.info("Watcher gestopt")
    conn.close()
    return 0


def _sleep_interruptible(seconds: int) -> None:
    """Sleep maar reageer op signals."""
    for _ in range(seconds):
        if not _running:
            return
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
