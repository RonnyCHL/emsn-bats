"""Configuratie voor EMSN Sonar - instelbaar via Web UI."""

from scripts.core.database import get_setting, set_setting

# Standaard instellingen
DEFAULTS = {
    # Opname
    "recording.enabled": "true",
    "recording.night_only": "true",
    "recording.sample_rate": "200000",
    "recording.duration_seconds": "5",
    "recording.device_name": "UltraMic",
    "recording.channels": "1",
    # Detectie
    "detection.threshold": "0.3",
    "detection.species_threshold": "0.2",
    # Opslag
    "storage.recordings_dir": "/home/ronny/emsn-sonar/recordings",
    "storage.spectrograms_dir": "/home/ronny/emsn-sonar/spectrograms",
    "storage.retention_days": "30",
    # Web UI
    "web.port": "8088",
    "web.host": "0.0.0.0",
    # Station
    "station.name": "emsn-sonar",
    "station.location": "Nijverdal",
    "station.lat": "52.360179",
    "station.lon": "6.472626",
}


def get_config(key: str) -> str:
    """Haal config waarde op, met fallback naar default."""
    return get_setting(key, DEFAULTS.get(key, ""))


def set_config(key: str, value: str):
    """Sla config waarde op."""
    set_setting(key, value)


def get_all_config() -> dict[str, str]:
    """Haal alle config op (defaults + overrides)."""
    config = dict(DEFAULTS)
    from scripts.core.database import get_connection

    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        config[row["key"]] = row["value"]
    return config


def get_config_bool(key: str) -> bool:
    """Haal boolean config op."""
    return get_config(key).lower() in ("true", "1", "yes")


def get_config_int(key: str) -> int:
    """Haal integer config op."""
    return int(get_config(key))


def get_config_float(key: str) -> float:
    """Haal float config op."""
    return float(get_config(key))


def init_defaults():
    """Zet standaard instellingen als ze niet bestaan."""
    from scripts.core.database import get_connection

    conn = get_connection()
    for key, value in DEFAULTS.items():
        existing = conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if not existing:
            set_setting(key, value)
