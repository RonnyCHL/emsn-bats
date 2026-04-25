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


def _on_disconnect(_client_, _userdata, _flags, reason_code, _properties):
    global _connected
    _connected = False
    _connected_event.clear()
    # rc=0 = wij hebben zelf disconnect() gecalled (clean shutdown).
    if int(reason_code) != 0:
        logger.warning("MQTT verbinding verbroken (rc=%s), paho herverbindt", reason_code)


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


def _publish(topic: str, payload: str, *, qos: int = 1, retain: bool = False) -> bool:
    """Interne publish helper. Wacht kort op de eerste connectie."""
    client = _get_client()
    if client is None:
        return False
    if not _connected:
        # Eerste publish na proces-start: paho is mogelijk nog bezig met
        # de TCP-handshake. Geef het even de tijd. Daarna geven we op
        # zodat een lange-running detector niet vastloopt op een dode
        # broker.
        if not _connected_event.wait(_INITIAL_CONNECT_TIMEOUT):
            logger.debug("MQTT niet verbonden binnen %.1fs, skip %s",
                         _INITIAL_CONNECT_TIMEOUT, topic)
            return False
    try:
        info = client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish faalde topic=%s rc=%d", topic, info.rc)
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
        return True
    except Exception:
        logger.exception("MQTT publish exception topic=%s", topic)
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
