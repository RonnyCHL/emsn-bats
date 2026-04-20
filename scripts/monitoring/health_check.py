"""Health check voor EMSN Sonar.

Controleert alle componenten en publiceert status naar MQTT.
"""

import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from scripts.core.config import get_config
from scripts.core.database import get_connection, get_today_stats, init_db

logger = logging.getLogger("bat_health")

SERVICES = [
    "sonar-monitor.service",
    "emsn-sonar-web.service",
]

TIMERS = [
    "sonar-cleanup.timer",
    "sonar-batdetect2-sync.timer",
]


def check_service_status(name: str) -> dict:
    """Check of een systemd service actief is."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        active = result.stdout.strip() == "active"
        return {"name": name, "active": active, "status": result.stdout.strip()}
    except Exception as e:
        return {"name": name, "active": False, "status": str(e)}


def check_disk_space() -> dict:
    """Check beschikbare schijfruimte."""
    usage = shutil.disk_usage("/")
    return {
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
        "percent": round(usage.used / usage.total * 100, 1),
    }


def check_ultramic() -> dict:
    """Check of de Ultramic aangesloten is."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        for d in devices:
            if "UltraMic" in d["name"]:
                return {
                    "connected": True,
                    "name": d["name"],
                    "sample_rate": d["default_samplerate"],
                }
        return {"connected": False}
    except Exception as e:
        return {"connected": False, "error": str(e)}


def check_cpu_temp() -> float | None:
    """Lees CPU temperatuur."""
    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            return int(temp_path.read_text().strip()) / 1000.0
    except Exception:
        pass
    return None


def check_nas_mount() -> bool:
    """Check of NAS gemount is."""
    return Path("/mnt/nas-birdnet-archive").is_mount()


def run_health_check() -> dict:
    """Voer volledige health check uit."""
    init_db()

    health = {
        "timestamp": datetime.now().isoformat(),
        "station": "emsn-sonar",
        "services": [check_service_status(s) for s in SERVICES],
        "timers": [check_service_status(t) for t in TIMERS],
        "disk": check_disk_space(),
        "ultramic": check_ultramic(),
        "cpu_temp": check_cpu_temp(),
        "nas_mounted": check_nas_mount(),
        "stats": get_today_stats(),
    }

    # Overall status
    all_services_ok = all(s["active"] for s in health["services"])
    mic_ok = health["ultramic"]["connected"]
    disk_ok = health["disk"]["percent"] < 90

    health["overall"] = "ok" if (all_services_ok and mic_ok and disk_ok) else "warning"
    if not mic_ok:
        health["overall"] = "error"

    return health


def main():
    """Entry point - print en publiceer health status."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    health = run_health_check()

    # Print
    print(json.dumps(health, indent=2, ensure_ascii=False))

    # Publiceer naar MQTT
    try:
        from scripts.detection.mqtt_publisher import publish_health

        publish_health(health)
        logger.info("Health status gepubliceerd naar MQTT")
    except Exception:
        logger.exception("MQTT health publish mislukt")


if __name__ == "__main__":
    main()
