"""Smoke test: alle EMSN Sonar modules moeten importeren.

Geeft een vroege regressie-detector voor breaking dependency updates
(bv. het ai-edge-litert 2.x incident van april 2026 zou hier opduiken
als ImportError of AttributeError tijdens import).
"""

from __future__ import annotations

import importlib

import pytest

# Modules die tijdens import al externe state kunnen aantikken
# (audio device probe, MQTT init, DB connect) skippen we hier — die
# horen in hun eigen functionele tests.
_SKIP_MODULES = {
    "scripts.detection.sonar_monitor",  # importeert sounddevice/batdetect2
    "scripts.bavaria.bavaria_watcher",  # subprocess naar BattyBirdNET
    "scripts.web.app",                  # Flask app, port binding
}

_MODULES_TO_IMPORT = [
    "scripts.core.config",
    "scripts.core.database",
    "scripts.core.secrets",
    "scripts.core.species",
    "scripts.core.sun",
    "scripts.core.systemd_notify",
    "scripts.detection.mqtt_publisher",
    "scripts.detection.spectrogram",
    "scripts.detection.time_stretch",
    "scripts.monitoring.detection_silence_check",
    "scripts.monitoring.ha_mqtt_discovery",
    "scripts.monitoring.hardware_monitor",
    "scripts.monitoring.health_check",
    "scripts.monitoring.reboot_alert",
    "scripts.monitoring.stats_publisher",
    "scripts.sync.batdetect2_sync",
    "scripts.sync.bavaria_sync",
]


@pytest.mark.parametrize("module_name", _MODULES_TO_IMPORT)
def test_module_importable(module_name: str) -> None:
    """Module moet importeerbaar zijn zonder side effects te crashen."""
    if module_name in _SKIP_MODULES:
        pytest.skip(f"{module_name} heeft external state bij import")
    importlib.import_module(module_name)
