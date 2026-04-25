"""MQTT publisher voor vleermuisdetecties.

Publiceert live detecties naar de EMSN MQTT broker. Wordt aangeroepen
vanuit zowel sonar_monitor.py (BatDetect2) als bavaria_watcher.py.

Ontwerp (na incident 2026-04-22 — FD-leak loop):

* Eén persistente client per proces (singleton), eenmalig opgezet.
* Unieke client_id per proces (rol + PID) zodat sonar-monitor en
  sonar-bavaria elkaar nooit kunnen kicken op de broker.
* Paho's interne reconnect_delay_set() doet alle reconnects; we maken
  nooit handmatig een tweede mqtt.Client aan. Hierdoor is een
  thread/socket-leak structureel onmogelijk.
* Thread-safe via een module-Lock.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import sys
import threading
from pathlib import Path

import paho.mqtt.client as mqtt

from scripts.core.secrets import get_mqtt_config

logger = logging.getLogger(__name__)

# MQTT Topics - gedeeld door beide detector-processen.
# De detector wordt als veld in de JSON payload meegestuurd.
TOPIC_DETECTION = "emsn2/sonar/detection"
TOPIC_STATS = "emsn2/sonar/stats"
TOPIC_HEALTH = "emsn2/sonar/health"

# Paho reconnect-window (seconden). Paho's loop thread reconnect zelf
# binnen dit window; wij hoeven niets te doen behalve publish() callen.
_RECONNECT_MIN_DELAY = 1
_RECONNECT_MAX_DELAY = 120

# Hoe lang we bij de eerste publish wachten op een initiële connectie
# voordat we opgeven (kortlevende processen zoals stats_publisher).
_INITIAL_CONNECT_TIMEOUT = 5.0

_client: mqtt.Client | None = None
_connected = False
_init_lock = threading.Lock()
_connected_event = threading.Event()

# Aantal opeenvolgende failed publishes sinds de laatste succesvolle. Wordt
# door long-running detectors uitgelezen (zie ``get_publish_failure_streak``)
# om te beslissen of ze zichzelf moeten herstarten - dat is de tweede
# verdedigingslinie naast de FD self-check sinds incident 2026-04-22, voor
# scenario's waarin we nog wel FDs hebben maar de broker structureel
# onbereikbaar is.
_publish_failure_streak = 0
_publish_streak_lock = threading.Lock()


def _build_client_id() -> str:
    """Bouw een client_id die uniek is per proces.

    Twee services (sonar-monitor en sonar-bavaria) draaien naast
    elkaar en importeren beide deze module. Een gedeelde client_id zou
    de broker dwingen om de eerste verbinding te kicken zodra de
    tweede zich meldt (MQTT 3.1.1 spec). Dat veroorzaakte in april
    2026 een reconnect-storm met thread + FD-leak.

    Vorm: ``emsn-sonar-<argv0>-<host>-<pid>``.
    """
    role = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "py"
    return f"emsn-sonar-{role or 'py'}-{socket.gethostname()}-{os.getpid()}"


def _on_connect(_client_, _userdata, _flags, reason_code, _properties):
    global _connected
    if reason_code == 0:
        _connected = True
        _connected_event.set()
        logger.info("MQTT verbonden")
    else:
        _connected = False
        logger.warning("MQTT connect geweigerd: %s", reason_code)


_LAST_DISCONNECT_LOG_AT: float = 0.0
_DISCONNECT_LOG_THROTTLE_SEC = 300


def _on_disconnect(_client_, _userdata, _flags, reason_code, _properties):
    global _connected, _LAST_DISCONNECT_LOG_AT
    _connected = False
    _connected_event.clear()
    # rc=0 = wij hebben zelf disconnect() gecalled (clean shutdown).
    # Paho v2 levert een ReasonCode object zonder __int__ - vergelijk via .value.
    rc_value = getattr(reason_code, "value", reason_code)
    if rc_value == 0:
        return
    # Throttle: bij langdurige broker-uitval krijgen we elke
    # ``_RECONNECT_MAX_DELAY`` seconden een disconnect-callback. Een
    # warning per ~5 minuten is genoeg om de uitval-duur in de journal
    # te kunnen reconstrueren zonder dat we de logs vol pompen.
    import time as _time
    now = _time.monotonic()
    if now - _LAST_DISCONNECT_LOG_AT >= _DISCONNECT_LOG_THROTTLE_SEC:
        logger.warning("MQTT verbinding verbroken (rc=%s), paho herverbindt", reason_code)
        _LAST_DISCONNECT_LOG_AT = now


def _get_client() -> mqtt.Client | None:
    """Geef de singleton client (lazy init).

    Maakt de client genoeg op één plek aan en start ``loop_start()``
    één keer. Daarna draait paho zelf reconnects, dus volgende calls
    geven simpelweg dezelfde instance terug — ongeacht of we op dat
    moment verbonden zijn.
    """
    global _client

    if _client is not None:
        return _client

    with _init_lock:
        if _client is not None:
            return _client

        try:
            config = get_mqtt_config()
            if not config["password"]:
                logger.warning("Geen MQTT credentials geconfigureerd")
                return None

            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=_build_client_id(),
                clean_session=True,
            )
            client.username_pw_set(config["user"], config["password"])
            client.reconnect_delay_set(
                min_delay=_RECONNECT_MIN_DELAY,
                max_delay=_RECONNECT_MAX_DELAY,
            )
            client.on_connect = _on_connect
            client.on_disconnect = _on_disconnect

            client.connect_async(config["host"], config["port"], keepalive=60)
            client.loop_start()

            _client = client
            atexit.register(disconnect)
            return _client

        except Exception:
            logger.exception("MQTT client initialisatie mislukt")
            return None


def _record_publish_result(success: bool) -> None:
    """Update de globale publish-failure streak counter."""
    global _publish_failure_streak
    with _publish_streak_lock:
        if success:
            _publish_failure_streak = 0
        else:
            _publish_failure_streak += 1


def get_publish_failure_streak() -> int:
    """Aantal opeenvolgende failed publishes sinds laatste succes.

    Long-running detectors kunnen dit gebruiken om bij een aanhoudend
    onbereikbare broker zichzelf te laten herstarten i.p.v. door te
    blijven proberen.
    """
    with _publish_streak_lock:
        return _publish_failure_streak


def _publish(topic: str, payload: str, *, qos: int = 1, retain: bool = False) -> bool:
    """Interne publish helper. Wacht kort op de eerste connectie."""
    client = _get_client()
    if client is None:
        _record_publish_result(False)
        return False
    if not _connected:
        # Eerste publish na proces-start: paho is mogelijk nog bezig met
        # de TCP-handshake. Geef het even de tijd. Daarna geven we op
        # zodat een lange-running detector niet vastloopt op een dode
        # broker.
        if not _connected_event.wait(_INITIAL_CONNECT_TIMEOUT):
            logger.debug("MQTT niet verbonden binnen %.1fs, skip %s",
                         _INITIAL_CONNECT_TIMEOUT, topic)
            _record_publish_result(False)
            return False
    try:
        info = client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish faalde topic=%s rc=%d", topic, info.rc)
            _record_publish_result(False)
            return False
        # Voor qos>0: kort wachten tot broker PUBACK stuurt zodat
        # kortlevende processen niet exiten voordat de boodschap weg is.
        if qos > 0:
            try:
                info.wait_for_publish(timeout=2.0)
            except (ValueError, RuntimeError):
                # ValueError: client niet meer connected; RuntimeError:
                # loop_stop al gebeurd. Beide niet-fataal hier.
                pass
        _record_publish_result(True)
        return True
    except Exception:
        logger.exception("MQTT publish exception topic=%s", topic)
        _record_publish_result(False)
        return False


def publish_detection(detection: dict) -> bool:
    """Publiceer een vleermuisdetectie naar MQTT.

    Args:
        detection: Dict met detection_time, species, species_dutch,
                   confidence, frequency_low/high/peak, duration_ms,
                   station, detector.

    Returns:
        True als succesvol naar broker gestuurd.
    """
    payload = json.dumps(
        {
            "timestamp": detection.get("detection_time"),
            "species": detection.get("species"),
            "species_dutch": detection.get("species_dutch"),
            "confidence": round(detection.get("confidence", 0), 3),
            "det_prob": round(detection.get("det_prob", 0), 3),
            "frequency_low": detection.get("frequency_low"),
            "frequency_high": detection.get("frequency_high"),
            "frequency_peak": detection.get("frequency_peak"),
            "duration_ms": round(detection.get("duration_ms", 0), 1),
            "station": detection.get("station", "emsn-sonar"),
            "detector": detection.get("detector", "batdetect2"),
        },
        ensure_ascii=False,
    )
    return _publish(TOPIC_DETECTION, payload)


def publish_stats(stats: dict) -> bool:
    """Publiceer statistieken (retained)."""
    return _publish(TOPIC_STATS, json.dumps(stats, ensure_ascii=False), retain=True)


def publish_health(status: dict) -> bool:
    """Publiceer health status (retained)."""
    return _publish(TOPIC_HEALTH, json.dumps(status, ensure_ascii=False), retain=True)


def disconnect() -> None:
    """Sluit MQTT verbinding netjes (te callen bij shutdown)."""
    global _client, _connected
    if _client is not None:
        try:
            _client.loop_stop()
            _client.disconnect()
        except Exception:
            logger.exception("MQTT disconnect fout")
        finally:
            _client = None
            _connected = False
