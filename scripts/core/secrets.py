"""Secrets loader - leest credentials uit .secrets bestand."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_secrets: dict[str, str] = {}
_SECRETS_PATH = Path.home() / "emsn-bats" / ".secrets"


def _load_secrets() -> dict[str, str]:
    """Laad secrets uit .secrets bestand (lazy, eenmalig)."""
    global _secrets
    if _secrets:
        return _secrets

    if not _SECRETS_PATH.exists():
        logger.warning("Secrets bestand niet gevonden: %s", _SECRETS_PATH)
        return _secrets

    for line in _SECRETS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            _secrets[key.strip()] = value.strip()

    logger.info("Secrets geladen: %d entries", len(_secrets))
    return _secrets


def get_secret(key: str, default: str = "") -> str:
    """Haal een secret op uit .secrets."""
    return _load_secrets().get(key, default)


def get_pg_config() -> dict[str, str]:
    """PostgreSQL configuratie."""
    secrets = _load_secrets()
    return {
        "host": secrets.get("PG_HOST", "192.168.1.25"),
        "port": secrets.get("PG_PORT", "5433"),
        "dbname": secrets.get("PG_DB", "emsn"),
        "user": secrets.get("PG_USER", "birdpi_zolder"),
        "password": secrets.get("PG_PASS", ""),
    }


def get_mqtt_config() -> dict[str, str]:
    """MQTT configuratie."""
    secrets = _load_secrets()
    return {
        "host": secrets.get("MQTT_HOST", "192.168.1.178"),
        "port": int(secrets.get("MQTT_PORT", "1883")),
        "user": secrets.get("MQTT_USER", "ecomonitor"),
        "password": secrets.get("MQTT_PASS", ""),
    }


def get_nas_config() -> dict[str, str]:
    """NAS configuratie."""
    secrets = _load_secrets()
    return {
        "host": secrets.get("NAS_HOST", "192.168.1.25"),
        "user": secrets.get("NAS_USER", "ronny"),
        "password": secrets.get("NAS_PASS", ""),
    }
