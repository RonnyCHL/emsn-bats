"""Alarm wanneer sonar-monitor draait maar geen detecties produceert.

Achtergrond
===========

Op 22-25 april 2026 lekte de MQTT-publisher zoveel file descriptors dat
``sounddevice`` na ~3 dagen geen InputStream meer kon openen. ``systemctl
status`` zei nog "active (running)", de FD self-check (toegevoegd na het
incident) onderbreekt nu zulke processen, maar er was geen tweede laag die
detectie-stilte zelf opmerkte. Dit script is die tweede laag.

Werking
=======

Eén shot, periodiek getriggerd door ``sonar-detection-silence.timer``:

#. Bepaal of het op dit moment "actieve detectie-tijd" is. We kijken
   alleen tijdens de nacht (zelfde ``is_night()`` logica als sonar_monitor),
   plus een korte grace-periode na zonsondergang/voor zonsopgang waarin
   stilte normaal is.
#. Tel detecties in ``bats.db`` van de afgelopen ``BatDetect2`` window.
#. Als 0 detecties tijdens actieve nacht-tijd én er is geen plausibele
   uitleg (opname uitgeschakeld in settings, microfoon ontkoppeld), publish
   een retained MQTT alert op ``emsn2/sonar/health`` zodat de zolder
   ``health_alert_bridge`` het oppikt.

Het script staat heel bewust geen email of andere kanalen rechtstreeks
aan: alle alert-routing draait centraal vanuit emsn2.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from scripts.core.sun import is_night
from scripts.detection.mqtt_publisher import publish_health

logger = logging.getLogger("detection_silence_check")

DB_PATH: Path = Path.home() / "emsn-sonar" / "data" / "bats.db"

# Hoe ver terugkijken voor "is er recent gedetecteerd?". 2 uur is ruim
# genoeg om gaten in vleermuis-activiteit (rustige stukken in de nacht) te
# overbruggen, maar kort genoeg om stille degradatie binnen één nacht op
# te merken.
_LOOKBACK = timedelta(hours=2)

# Grace-periode rond zonsondergang/zonsopgang waarin stilte normaal is.
# is_night() heeft zelf al een marge van 30 minuten; we voegen daar nog
# een uur extra opwarmtijd aan toe zodat we niet direct na zonsondergang
# alarm slaan voordat er iets te detecteren valt.
_NIGHT_WARMUP = timedelta(hours=1)

# MQTT health-payload status codes die health_alert_bridge herkent.
_STATUS_OK = "ok"
_STATUS_SILENT = "no_detections"
_STATUS_DAYTIME = "daytime_idle"
_STATUS_DISABLED = "recording_disabled"


def _is_active_detection_window(now: datetime) -> bool:
    """Geeft True als sonar momenteel actief zou moeten detecteren.

    We rekenen alleen op detecties als het al minimaal ``_NIGHT_WARMUP``
    nacht is — vlak na zonsondergang is leegte normaal.
    """
    if not is_night():
        return False
    # is_night() kijkt naar "nu". We willen weten of we al een uur in de
    # nacht zijn. We berekenen dat door de zonsondergang/-opgang van
    # vandaag op te halen en zelf te vergelijken met (now - warmup).
    return _was_night_at(now - _NIGHT_WARMUP)


def _was_night_at(when: datetime) -> bool:
    """Check of ``when`` binnen het nacht-window van zijn datum viel.

    Werkt met zowel naïeve als tz-aware datetimes; we casten ``when``
    naar local tz om te matchen met de output van ``get_sun_times()``.
    """
    from scripts.core.sun import get_sun_times

    if when.tzinfo is None:
        when = when.astimezone()

    sunrise, sunset = get_sun_times(dt=when.date())
    margin = timedelta(minutes=30)
    if when >= (sunset - margin):
        return True
    if when <= (sunrise + margin):
        return True
    return False


def _count_recent_detections(db_path: Path, lookback: timedelta) -> int:
    """Tel detecties binnen ``lookback`` voor nu. 0 als DB ontbreekt."""
    if not db_path.exists():
        logger.warning("Detection DB ontbreekt: %s", db_path)
        return 0

    cutoff = (datetime.now() - lookback).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE detection_time >= ?",
            (cutoff,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _read_recording_enabled(db_path: Path) -> bool:
    """Lees de ``recording.enabled`` setting uit bats.db (default: True)."""
    if not db_path.exists():
        return True
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("recording.enabled",),
        ).fetchone()
        if not row:
            return True
        return str(row[0]).strip().lower() in ("true", "1", "yes", "on")
    except sqlite3.OperationalError:
        return True
    finally:
        conn.close()


def _build_payload(status: str, detail: str, count: int) -> dict:
    return {
        "component": "detection_silence_check",
        "status": status,
        "detail": detail,
        "detections_last_2h": count,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def evaluate(now: datetime | None = None) -> dict:
    """Bepaal de huidige status. Pure functie, eenvoudig te testen."""
    now = now or datetime.now().astimezone()

    if not _is_active_detection_window(now):
        return _build_payload(
            _STATUS_DAYTIME,
            "Buiten actieve detectie-window (dag of warm-up)",
            count=0,
        )

    if not _read_recording_enabled(DB_PATH):
        return _build_payload(
            _STATUS_DISABLED,
            "recording.enabled=false in settings - bewust uitgeschakeld",
            count=0,
        )

    count = _count_recent_detections(DB_PATH, _LOOKBACK)
    if count == 0:
        return _build_payload(
            _STATUS_SILENT,
            f"Geen detecties in laatste {int(_LOOKBACK.total_seconds() // 3600)}h "
            "tijdens actieve nacht - mogelijk hardware/pipeline probleem",
            count=0,
        )

    return _build_payload(
        _STATUS_OK,
        f"{count} detecties in laatste {int(_LOOKBACK.total_seconds() // 3600)}h",
        count=count,
    )


def main() -> int:
    """Entry point voor systemd timer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    payload = evaluate()
    logger.info(
        "Status=%s count=%d detail=%s",
        payload["status"],
        payload["detections_last_2h"],
        payload["detail"],
    )
    publish_health(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
