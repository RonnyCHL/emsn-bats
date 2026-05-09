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
from datetime import datetime, timedelta
from pathlib import Path

# Vaste paden - dit script draait altijd op de Sonar Pi
HOME = Path.home()
ANALYZER_DIR = HOME / "BattyBirdNET-Analyzer"
ANALYZER_VENV_PY = ANALYZER_DIR / "venv" / "bin" / "python3"
ANALYZER_SCRIPT = ANALYZER_DIR / "bat_ident.py"
DB_PATH = HOME / "emsn-sonar" / "data" / "batty_bavaria.db"
TMP_OUT_DIR = Path("/tmp/batty_results")

# Core-DB paden worden via de settings-tabel van bats.db opgehaald zodat
# we single-source-of-truth houden met sonar_monitor. Audit 2026-04-20 H3:
# hardcoded paden wezen naar lege directories na emsn-bats -> emsn-sonar rename.
CORE_DB_PATH = HOME / "emsn-sonar" / "data" / "bats.db"


def _read_core_setting(key: str, default: str) -> str:
    """Lees een setting uit de core bats.db, met fallback."""
    try:
        conn = sqlite3.connect(f"file:{CORE_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default
        finally:
            conn.close()
    except sqlite3.Error:
        return default


RECORDINGS_DIR = Path(
    _read_core_setting("storage.recordings_dir", str(HOME / "emsn-sonar" / "recordings"))
)
SPECTROGRAMS_DIR = Path(
    _read_core_setting("storage.spectrograms_dir", str(HOME / "emsn-sonar" / "spectrograms"))
) / "bavaria"

POLL_INTERVAL_SEC = 30
# Bavaria-classifier scoort op onze 200kHz USB-mic opnames een stuk lager
# dan zijn typische test-set. Empirisch (test 2026-04-25) komt zelfs een
# duidelijke Nyctalus leisleri call uit op ~0.04. 0.5 is dus onbruikbaar
# en verklaarde "0 detecties" naast het ai-edge-litert defect.
MIN_CONFIDENCE = 0.05
AREA = "Bavaria"
THREADS = 2

# Hospital-grade defaults voor health monitoring.
STATUS_LOG_INTERVAL_SEC = 300       # log een health-summary elke 5 min
WATCHDOG_HEARTBEAT_SEC = 30         # systemd WatchdogSec staat op 300
# Falen-streak voor escalatie: bat_ident produceert ~17 calls per uur in
# typische zomer-nacht. 25 opeenvolgende echte mislukkingen (dus geen
# wav_disappeared) duidt op een systeemprobleem dat aandacht behoeft.
PERSISTENT_FAILURE_STREAK = 25
RECOVERABLE_REASONS = {"wav_disappeared"}

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
            synced_to_pg INTEGER NOT NULL DEFAULT 0,
            spectrogram_path TEXT
        )
        """
    )
    # Migreer bestaande DBs zonder nieuwe kolommen (idempotent)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(detections)").fetchall()]
    if "synced_to_pg" not in cols:
        conn.execute(
            "ALTER TABLE detections ADD COLUMN synced_to_pg INTEGER NOT NULL DEFAULT 0"
        )
    if "spectrogram_path" not in cols:
        conn.execute("ALTER TABLE detections ADD COLUMN spectrogram_path TEXT")
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


def run_analyzer(wav_path: Path) -> tuple[Path | None, str | None]:
    """Roep bat_ident.py aan en geef pad naar output CSV terug.

    Returns:
        Tuple ``(csv_path, error_reason)``:
          - bij succes: ``(Path(csv), None)``
          - bij falen: ``(None, error_reason)`` met één van:
            * ``"wav_disappeared"`` - WAV is weg vóór bat_ident kon starten
              (race conditie met sonar-monitor cleanup)
            * ``"analyzer_timeout"`` - bat_ident hangt >120s
            * ``"analyzer_rc_nonzero"`` - bat_ident exit code != 0
            * ``"analyzer_no_csv"`` - bat_ident exit 0 maar produceerde
              geen output (bekende bat_ident bug bij file-open errors:
              de tool prints "Cannot open audio file" naar stdout en
              exit met rc=0 i.p.v. een non-zero code)
    """
    if not wav_path.exists():
        # sonar-monitor verwijdert WAVs zonder BatDetect2-detecties;
        # tussen onze glob en deze call kan de file dus verdwenen zijn.
        return None, "wav_disappeared"

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
        return None, "analyzer_timeout"
    if result.returncode != 0:
        log.warning(
            "bat_ident rc=%d op %s: %s",
            result.returncode,
            wav_path.name,
            result.stderr.strip()[:300],
        )
        return None, "analyzer_rc_nonzero"
    if not out_csv.exists():
        # rc=0 maar geen CSV - meestal "Cannot open audio file" in stdout.
        # Logging van eerste regel stdout zodat oorzaak zichtbaar is.
        first_line = (result.stdout or "").strip().splitlines()
        hint = first_line[-1][:200] if first_line else "(stdout leeg)"
        log.warning("bat_ident rc=0 maar geen CSV op %s: %s", wav_path.name, hint)
        return None, "analyzer_no_csv"
    return out_csv, None


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
                     common_name, confidence, model_area, inserted_at,
                     spectrogram_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    det.get("spectrogram_path"),
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


def _generate_spectrogram(wav_path: Path, detection: dict) -> Path | None:
    """Genereer een spectrogram PNG voor één Bavaria detectie.

    Gebruikt soundfile + numpy + matplotlib (geen extra dependencies nodig,
    al beschikbaar in BattyBirdNET-Analyzer venv).

    Returns:
        Pad naar PNG bestand, of None als genereren mislukte.
    """
    try:
        import numpy as np
        import soundfile as sf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    try:
        recorded_at = parse_recorded_at(wav_path)
        base_dt = datetime.fromisoformat(recorded_at)
        det_ts = base_dt + timedelta(seconds=detection["start_s"])
        date_dir = SPECTROGRAMS_DIR / det_ts.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        safe_species = detection["scientific_name"].replace(" ", "_")
        out_path = date_dir / (
            f"bavaria_{det_ts.strftime('%H-%M-%S')}_{safe_species}_"
            f"{int(detection['confidence'] * 100)}.png"
        )
        if out_path.exists():
            return out_path

        audio, sr = sf.read(str(wav_path), dtype="float32")
        start_sample = max(0, int(detection["start_s"] * sr))
        end_sample = min(len(audio), int(detection["end_s"] * sr))
        segment = audio[start_sample:end_sample]
        if len(segment) < sr // 100:  # < 10ms
            return None

        fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
        fig.patch.set_facecolor("#0A0A0A")
        ax.set_facecolor("#0A0A0A")
        ax.specgram(
            segment, NFFT=512, Fs=sr, noverlap=384, cmap="inferno",
            vmin=-100, vmax=-20,
        )
        ax.set_ylim(0, sr / 2)
        ax.set_xlabel("Tijd (s)", color="#A8A8A8")
        ax.set_ylabel("Frequentie (Hz)", color="#A8A8A8")
        ax.tick_params(colors="#A8A8A8")
        for spine in ax.spines.values():
            spine.set_color("#2A2A2A")
        title = (
            f"{detection.get('common_name') or detection['scientific_name']} · "
            f"{detection['confidence']:.2f} · Bavaria"
        )
        ax.set_title(title, color="#FF6B1A", fontsize=11, pad=10)
        fig.tight_layout()
        fig.savefig(str(out_path), facecolor=fig.get_facecolor())
        plt.close(fig)
        return out_path
    except Exception:
        log.exception("Spectrogram genereren mislukt voor %s", wav_path.name)
        return None


def _publish_to_mqtt(wav_path: Path, detections: list[dict]) -> None:
    """Publiceer Bavaria detecties naar MQTT (best effort, geen fail)."""
    if not detections:
        return
    try:
        # Lazy import - mqtt is optioneel, niet blokkerend
        from scripts.detection.mqtt_publisher import publish_detection
    except ImportError:
        return

    recorded_at = parse_recorded_at(wav_path)
    base_dt = datetime.fromisoformat(recorded_at)
    for det in detections:
        ts = base_dt + timedelta(seconds=det["start_s"])
        publish_detection({
            "detection_time": ts.isoformat(timespec="seconds"),
            "species": det["scientific_name"],
            "species_dutch": det["common_name"],
            "confidence": det["confidence"],
            "duration_ms": (det["end_s"] - det["start_s"]) * 1000,
            "station": "emsn-sonar",
            "detector": "bavaria",
        })


def process_one(conn: sqlite3.Connection, wav_path: Path) -> tuple[int, str | None]:
    """Verwerk één WAV.

    Returns:
        Tuple ``(num_detections, error_reason)``. ``error_reason`` is
        ``None`` bij succes, anders één van de categorieën uit
        :func:`run_analyzer` of ``"parse_error"``.
    """
    csv_path, error_reason = run_analyzer(wav_path)
    if csv_path is None:
        store_results(conn, wav_path, [], error=error_reason)
        return 0, error_reason
    try:
        detections = parse_csv(csv_path)
    except Exception:
        log.exception("CSV parse error op %s", wav_path.name)
        store_results(conn, wav_path, [], error="parse_error")
        try:
            csv_path.unlink()
        except OSError:
            pass
        return 0, "parse_error"
    # Genereer spectrogrammen vóór opslaan zodat het pad mee wordt geschreven
    for det in detections:
        spec = _generate_spectrogram(wav_path, det)
        if spec is not None:
            det["spectrogram_path"] = str(spec)
    store_results(conn, wav_path, detections)
    _publish_to_mqtt(wav_path, detections)
    try:
        csv_path.unlink()
    except OSError:
        pass
    if detections:
        names = ", ".join(
            f"{d['common_name']} ({d['confidence']:.2f})" for d in detections[:3]
        )
        log.info("%s -> %d detecties: %s", wav_path.name, len(detections), names)
    return len(detections), None


def _sd_notify(message: str) -> None:
    """Stuur een raw sd_notify message naar systemd over de NOTIFY_SOCKET.

    Inline implementatie zodat we niet afhankelijk zijn van het
    ``systemd-python`` package of ``scripts.core.systemd_notify``: dit
    script draait onder de BattyBirdNET-Analyzer venv die emsn-sonar's
    package niet kan importeren. Het sd_notify protocol is gewoon een
    UDP-write naar een UNIX domain socket.

    No-op buiten een ``Type=notify`` systemd context (NOTIFY_SOCKET
    unset).
    """
    import os
    import socket

    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        return
    try:
        # Abstract Linux socket (begin met '@') -> NUL-prefixed path
        addr = "\0" + sock_path[1:] if sock_path.startswith("@") else sock_path
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(message.encode("utf-8"))
    except OSError:
        # sd_notify mag NOOIT de service tot crash brengen.
        pass


def _try_systemd_notify(state: str) -> None:
    """Vertaal high-level state naar het juiste sd_notify protocol bericht."""
    if state == "ready":
        _sd_notify("READY=1")
    elif state == "watchdog":
        _sd_notify("WATCHDOG=1")
    elif state == "stopping":
        _sd_notify("STOPPING=1")
    else:
        _sd_notify(f"STATUS={state}")


class _HealthCounters:
    """Houdt success/failure counters bij voor health-summary en alerting."""

    def __init__(self) -> None:
        self.processed_total = 0
        self.detections_total = 0
        self.errors_by_reason: dict[str, int] = {}
        self.consecutive_real_failures = 0
        self.escalated_streak = False
        self.last_status_log_at = time.monotonic()

    def record(self, detections: int, error_reason: str | None) -> None:
        self.processed_total += 1
        self.detections_total += detections
        if error_reason is None:
            self.consecutive_real_failures = 0
            self.escalated_streak = False
        else:
            self.errors_by_reason[error_reason] = (
                self.errors_by_reason.get(error_reason, 0) + 1
            )
            if error_reason not in RECOVERABLE_REASONS:
                self.consecutive_real_failures += 1

    def maybe_log_summary(self) -> None:
        """Log een health-summary als ``STATUS_LOG_INTERVAL_SEC`` is verstreken."""
        now = time.monotonic()
        if now - self.last_status_log_at < STATUS_LOG_INTERVAL_SEC:
            return
        self.last_status_log_at = now
        if self.processed_total == 0:
            log.info("Health: geen WAVs verwerkt in laatste interval")
            return
        success = self.processed_total - sum(self.errors_by_reason.values())
        success_pct = 100.0 * success / self.processed_total
        breakdown = ", ".join(
            f"{r}={c}" for r, c in sorted(self.errors_by_reason.items())
        ) or "geen"
        log.info(
            "Health: %d processed, %d detecties, %.0f%% success, errors: %s",
            self.processed_total,
            self.detections_total,
            success_pct,
            breakdown,
        )


def main() -> int:
    if not ANALYZER_SCRIPT.exists():
        log.error("bat_ident.py niet gevonden op %s", ANALYZER_SCRIPT)
        return 1
    if not ANALYZER_VENV_PY.exists():
        log.error("Analyzer venv python niet gevonden op %s", ANALYZER_VENV_PY)
        return 1
    conn = init_db()
    # Effectieve config-banner. Maakt verkeerde drempels en pad-mismatches
    # direct zichtbaar bij service-start (incident april 2026: 0.5 was te
    # hoog, alle detecties werden gefilterd).
    log.info(
        "BattyBirdNET watcher effectieve config:\n"
        "  area          = %s\n"
        "  kHz           = 256\n"
        "  min_conf      = %.3f\n"
        "  threads       = %d\n"
        "  poll_interval = %ds\n"
        "  recordings_dir = %s\n"
        "  spectrograms_dir = %s\n"
        "  analyzer       = %s\n"
        "  db_path        = %s\n"
        "  status_log     = elke %ds\n"
        "  watchdog       = elke %ds\n"
        "  failure_streak = alert na %d echte mislukkingen",
        AREA,
        MIN_CONFIDENCE,
        THREADS,
        POLL_INTERVAL_SEC,
        RECORDINGS_DIR,
        SPECTROGRAMS_DIR,
        ANALYZER_SCRIPT,
        DB_PATH,
        STATUS_LOG_INTERVAL_SEC,
        WATCHDOG_HEARTBEAT_SEC,
        PERSISTENT_FAILURE_STREAK,
    )

    _try_systemd_notify("ready")
    _try_systemd_notify("Monitoring actief")
    last_watchdog = time.monotonic()
    counters = _HealthCounters()
    iterations_idle = 0

    while _running:
        try:
            now = time.monotonic()
            if now - last_watchdog >= WATCHDOG_HEARTBEAT_SEC:
                _try_systemd_notify("watchdog")
                last_watchdog = now

            counters.maybe_log_summary()

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
                    detections, error_reason = process_one(conn, wav)
                except Exception:
                    log.exception("Fout bij verwerken %s", wav)
                    store_results(conn, wav, [], error="exception")
                    counters.record(0, "exception")
                else:
                    counters.record(detections, error_reason)

                if (
                    counters.consecutive_real_failures
                    >= PERSISTENT_FAILURE_STREAK
                    and not counters.escalated_streak
                ):
                    log.error(
                        "Persistent failure streak: %d opeenvolgende echte "
                        "mislukkingen (excl. wav_disappeared). Recente "
                        "errors: %s",
                        counters.consecutive_real_failures,
                        counters.errors_by_reason,
                    )
                    counters.escalated_streak = True
                # Heartbeat ook tussen WAV-verwerking voor langere queues.
                if time.monotonic() - last_watchdog >= WATCHDOG_HEARTBEAT_SEC:
                    _try_systemd_notify("watchdog")
                    last_watchdog = time.monotonic()
        except Exception:
            log.exception("Onverwachte fout in main loop")
            _sleep_interruptible(POLL_INTERVAL_SEC)

    _try_systemd_notify("stopping")
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
