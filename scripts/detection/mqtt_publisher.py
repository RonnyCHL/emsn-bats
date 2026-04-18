"""MQTT publisher voor vleermuisdetecties.

Publiceert live detecties naar de EMSN MQTT broker.
Wordt aangeroepen vanuit sonar_monitor.py bij elke detectie.
"""

import json
import logging
import time

import paho.mqtt.client as mqtt

from scripts.core.secrets import get_mqtt_config

logger = logging.getLogger(__name__)

_client: mqtt.Client | None = None
_connected = False

# MQTT Topics - gebruikt door sonar-monitor (BatDetect2) en sonar-bavaria (Bavaria)
# De detector wordt als key in het JSON payload opgenomen.
TOPIC_DETECTION = "emsn2/sonar/detection"
TOPIC_STATS = "emsn2/sonar/stats"
TOPIC_HEALTH = "emsn2/sonar/health"


def _get_client() -> mqtt.Client | None:
    """Lazy MQTT client initialisatie met reconnect."""
    global _client, _connected

    if _client is not None and _connected:
        return _client

    try:
        config = get_mqtt_config()
        if not config["password"]:
            logger.warning("Geen MQTT credentials geconfigureerd")
            return None

        _client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="emsn-sonar-publisher",
        )
        _client.username_pw_set(config["user"], config["password"])

        def on_connect(client, userdata, flags, reason_code, properties):
            global _connected
            if reason_code == 0:
                _connected = True
                logger.info("MQTT verbonden met %s", config["host"])
            else:
                _connected = False
                logger.warning("MQTT verbinding mislukt: %s", reason_code)

        def on_disconnect(client, userdata, flags, reason_code, properties):
            global _connected
            _connected = False
            logger.warning("MQTT verbinding verbroken: %s", reason_code)

        _client.on_connect = on_connect
        _client.on_disconnect = on_disconnect
        _client.loop_start()
        _client.connect(config["host"], config["port"], keepalive=60)

        # Wacht kort op verbinding
        for _ in range(10):
            if _connected:
                break
            time.sleep(0.1)

        return _client if _connected else None

    except Exception:
        logger.exception("MQTT client initialisatie mislukt")
        _client = None
        _connected = False
        return None


def publish_detection(detection: dict) -> bool:
    """Publiceer een vleermuisdetectie naar MQTT.

    Args:
        detection: Dict met detection_time, species, species_dutch,
                   confidence, frequency_low, frequency_high, etc.

    Returns:
        True als succesvol gepubliceerd.
    """
    client = _get_client()
    if client is None:
        return False

    try:
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

        result = client.publish(TOPIC_DETECTION, payload, qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug("MQTT detectie gepubliceerd: %s", detection.get("species"))
            return True
        else:
            logger.warning("MQTT publish mislukt: rc=%d", result.rc)
            return False

    except Exception:
        logger.exception("MQTT publish fout")
        return False


def publish_stats(stats: dict) -> bool:
    """Publiceer statistieken naar MQTT (retained)."""
    client = _get_client()
    if client is None:
        return False

    try:
        payload = json.dumps(stats, ensure_ascii=False)
        result = client.publish(TOPIC_STATS, payload, qos=1, retain=True)
        return result.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception:
        logger.exception("MQTT stats publish fout")
        return False


def publish_health(status: dict) -> bool:
    """Publiceer health status naar MQTT (retained)."""
    client = _get_client()
    if client is None:
        return False

    try:
        payload = json.dumps(status, ensure_ascii=False)
        result = client.publish(TOPIC_HEALTH, payload, qos=1, retain=True)
        return result.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception:
        logger.exception("MQTT health publish fout")
        return False


def disconnect():
    """Sluit MQTT verbinding."""
    global _client, _connected
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
        _connected = False
