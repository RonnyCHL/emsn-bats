"""EMSN Sonar Reboot Alert Service.

Detecteert reboots en publiceert MQTT alert bij elke boot. Onderscheidt
clean shutdowns (expected) van onverwachte reboots (watchdog, kernel panic,
power loss) door kernel ring buffer en systemd shutdown journal te checken.

Draait eenmalig bij boot via systemd (Type=oneshot).
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from scripts.core.secrets import get_mqtt_config

logger = logging.getLogger("reboot_alert")

STATE_FILE: Path = Path("/var/lib/emsn-sonar/reboot_state.json")
TOPIC_REBOOT: str = "emsn2/sonar/reboot"
TOPIC_ALERT: str = "emsn2/alerts"


def _classify_last_shutdown() -> tuple[str, str]:
    """Classificeer hoe de vorige shutdown gebeurde.

    Returns:
        Tuple (type, reason) waar type in {clean, watchdog, oom, panic,
        power_loss, unknown}.
    """
    try:
        result = subprocess.run(
            ["journalctl", "-b", "-1", "--no-pager", "-q"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        log = result.stdout.lower()
    except subprocess.SubprocessError:
        return "unknown", "Kon vorige boot log niet lezen"

    if "kernel panic" in log:
        return "panic", "Kernel panic in vorige boot"
    if "watchdog" in log and "reset" in log:
        return "watchdog", "Hardware watchdog reset"
    if "out of memory" in log or "oom-killer" in log:
        return "oom", "Out of memory killer"
    if "reached target shutdown" in log or "reboot: restarting system" in log:
        return "clean", "Clean shutdown/reboot"
    if not log.strip():
        return "power_loss", "Geen logs in vorige boot (waarschijnlijk power loss)"
    return "unknown", "Onbekende oorzaak"


def _get_uptime_seconds() -> float:
    """Lees uptime uit /proc/uptime."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return 0.0


def _load_previous_state() -> dict:
    """Laad vorige boot state (wordt gebruikt om reboots te detecteren)."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    """Persist state voor volgende boot vergelijking."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _publish_mqtt(topic: str, payload: dict, retain: bool = True) -> bool:
    """Publiceer MQTT bericht met retained flag. Return True bij succes."""
    config = get_mqtt_config()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "emsn-sonar-reboot-alert")
    if config.get("user"):
        client.username_pw_set(config["user"], config["password"])
    try:
        client.connect(config["host"], config["port"], 10)
        client.loop_start()
        info = client.publish(topic, json.dumps(payload), qos=1, retain=retain)
        info.wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
        return info.is_published()
    except (TimeoutError, OSError):
        logger.exception("MQTT publish faalde op topic %s", topic)
        return False


def main() -> int:
    """Entry point - detecteer reboot type en publiceer."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    hostname = socket.gethostname()
    now = datetime.now().isoformat(timespec="seconds")
    uptime = _get_uptime_seconds()

    shutdown_type, shutdown_reason = _classify_last_shutdown()
    previous = _load_previous_state()

    payload = {
        "hostname": hostname,
        "boot_at": now,
        "uptime_sec": uptime,
        "previous_boot_at": previous.get("boot_at"),
        "last_shutdown_type": shutdown_type,
        "last_shutdown_reason": shutdown_reason,
    }

    logger.info(
        "Boot detected: type=%s reason=%s", shutdown_type, shutdown_reason
    )

    # Persistent retained bericht met laatste boot info
    _publish_mqtt(TOPIC_REBOOT, payload, retain=True)

    # Extra alert bij onverwachte reboots (niet retained, historie via MQTT broker)
    if shutdown_type in {"watchdog", "oom", "panic", "power_loss"}:
        alert = {
            "severity": "warning" if shutdown_type == "power_loss" else "error",
            "station": "emsn-sonar",
            "event": "unexpected_reboot",
            "type": shutdown_type,
            "reason": shutdown_reason,
            "timestamp": now,
        }
        _publish_mqtt(TOPIC_ALERT, alert, retain=False)
        logger.warning("Unexpected reboot alert verzonden")

    _save_state({"boot_at": now, "last_shutdown_type": shutdown_type})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
