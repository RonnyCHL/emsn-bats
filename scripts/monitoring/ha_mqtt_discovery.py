"""Home Assistant MQTT Discovery voor EMSN Sonar.

Publiceert MQTT Discovery configs zodat Home Assistant automatisch
sensoren aanmaakt voor vandaag's detecties, soorten, actieve detector, etc.

Draait eenmaal bij boot (via systemd one-shot) zodat HA ook na een HA
restart de devices terug vindt via retained discovery messages.
"""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from scripts.core.secrets import get_mqtt_config

logger = logging.getLogger("ha_mqtt_discovery")

STATION = "emsn-sonar"
DEVICE = {
    "identifiers": [STATION],
    "name": "EMSN Sonar",
    "manufacturer": "EMSN",
    "model": "Dual detection - BatDetect2 + BattyBirdNET-Bavaria",
    "configuration_url": "http://192.168.1.88:8088",
    "sw_version": "1.0",
}

# Discovery sensoren - elke sensor publiceert naar z'n eigen state topic,
# state wordt geleverd door sonar-monitor + bavaria MQTT publish_stats()
SENSORS: list[dict] = [
    {
        "unique_id": "emsn_sonar_detections_today",
        "name": "Detecties Vandaag",
        "state_topic": "emsn2/sonar/stats",
        "value_template": "{{ value_json.today | default(0) }}",
        "icon": "mdi:bat",
        "state_class": "total",
    },
    {
        "unique_id": "emsn_sonar_species_today",
        "name": "Soorten Vandaag",
        "state_topic": "emsn2/sonar/stats",
        "value_template": "{{ value_json.species_today | default(0) }}",
        "icon": "mdi:paw",
        "state_class": "measurement",
    },
    {
        "unique_id": "emsn_sonar_detections_total",
        "name": "Detecties Totaal",
        "state_topic": "emsn2/sonar/stats",
        "value_template": "{{ value_json.total | default(0) }}",
        "icon": "mdi:bat",
        "state_class": "total_increasing",
    },
    {
        "unique_id": "emsn_sonar_last_species",
        "name": "Laatste Soort",
        "state_topic": "emsn2/sonar/detection",
        "value_template": "{{ value_json.species_dutch | default(value_json.species) }}",
        "icon": "mdi:owl",
    },
    {
        "unique_id": "emsn_sonar_last_confidence",
        "name": "Laatste Confidence",
        "state_topic": "emsn2/sonar/detection",
        "value_template": "{{ (value_json.confidence | float * 100) | round(0) }}",
        "unit_of_measurement": "%",
        "icon": "mdi:percent",
    },
    {
        "unique_id": "emsn_sonar_last_detector",
        "name": "Laatste Detector",
        "state_topic": "emsn2/sonar/detection",
        "value_template": "{{ value_json.detector | default('batdetect2') }}",
        "icon": "mdi:radar",
    },
]

BINARY_SENSORS: list[dict] = [
    {
        "unique_id": "emsn_sonar_online",
        "name": "Online",
        "state_topic": "emsn2/sonar/health",
        "value_template": "{{ 'ON' if value_json.online | default(false) else 'OFF' }}",
        "device_class": "connectivity",
        "icon": "mdi:connection",
    },
]


def _publish_configs(client: mqtt.Client) -> int:
    """Publiceer alle discovery configs als retained messages."""
    count = 0
    for sensor in SENSORS:
        config = {**sensor, "device": DEVICE}
        topic = f"homeassistant/sensor/{sensor['unique_id']}/config"
        info = client.publish(topic, json.dumps(config), qos=1, retain=True)
        info.wait_for_publish(timeout=5)
        count += 1
        logger.info("Published %s", topic)

    for sensor in BINARY_SENSORS:
        config = {**sensor, "device": DEVICE}
        topic = f"homeassistant/binary_sensor/{sensor['unique_id']}/config"
        info = client.publish(topic, json.dumps(config), qos=1, retain=True)
        info.wait_for_publish(timeout=5)
        count += 1
        logger.info("Published %s", topic)

    return count


def main() -> int:
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = get_mqtt_config()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, "emsn-sonar-ha-discovery"
    )
    if config.get("user"):
        client.username_pw_set(config["user"], config["password"])

    try:
        client.connect(config["host"], config["port"], 10)
        client.loop_start()
        count = _publish_configs(client)
        client.loop_stop()
        client.disconnect()
        logger.info("HA Discovery voltooid: %d sensors gepubliceerd", count)
        return 0
    except (TimeoutError, OSError):
        logger.exception("MQTT verbinding mislukt")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
