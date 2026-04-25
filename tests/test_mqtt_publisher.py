"""Unit tests voor scripts.detection.mqtt_publisher.

Vangt de incident-categorie van 22 april 2026 (gedeelde client_id +
thread leak) door de structurele invarianten te verifiëren in plaats
van de werking tegen een echte broker.
"""

from __future__ import annotations

import socket
from typing import Iterator

import pytest

from scripts.detection import mqtt_publisher


@pytest.fixture(autouse=True)
def _reset_module_state() -> Iterator[None]:
    """Forceer een schone module-state per test."""
    mqtt_publisher._client = None
    mqtt_publisher._connected = False
    mqtt_publisher._connected_event.clear()
    mqtt_publisher._publish_failure_streak = 0
    yield
    mqtt_publisher._client = None
    mqtt_publisher._connected = False
    mqtt_publisher._connected_event.clear()
    mqtt_publisher._publish_failure_streak = 0


def test_client_id_is_unique_per_process() -> None:
    """De client_id moet hostname én PID bevatten zodat twee processen
    op dezelfde machine elkaar nooit kunnen kicken op de broker."""
    client_id = mqtt_publisher._build_client_id()

    assert socket.gethostname() in client_id, (
        "client_id moet hostname bevatten voor cross-host disambiguation"
    )
    import os
    assert str(os.getpid()) in client_id, (
        "client_id moet PID bevatten zodat twee processen op dezelfde "
        "host (sonar-monitor + sonar-bavaria) verschillende ids krijgen"
    )
    assert client_id.startswith("emsn-sonar-"), (
        "client_id moet herkenbare prefix hebben"
    )


def test_failure_streak_starts_at_zero() -> None:
    assert mqtt_publisher.get_publish_failure_streak() == 0


def test_failure_streak_increments_on_failure() -> None:
    mqtt_publisher._record_publish_result(success=False)
    mqtt_publisher._record_publish_result(success=False)
    mqtt_publisher._record_publish_result(success=False)
    assert mqtt_publisher.get_publish_failure_streak() == 3


def test_failure_streak_resets_on_success() -> None:
    mqtt_publisher._record_publish_result(success=False)
    mqtt_publisher._record_publish_result(success=False)
    mqtt_publisher._record_publish_result(success=True)
    assert mqtt_publisher.get_publish_failure_streak() == 0


def test_failure_streak_thread_safe() -> None:
    """Concurrent recordings moeten alle calls tellen, geen race-loss."""
    import threading

    n_per_thread = 100
    n_threads = 8

    def worker() -> None:
        for _ in range(n_per_thread):
            mqtt_publisher._record_publish_result(success=False)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert mqtt_publisher.get_publish_failure_streak() == n_per_thread * n_threads


def test_publish_returns_false_when_no_credentials(monkeypatch) -> None:
    """Zonder credentials moet publish stilletjes False geven, geen crash."""
    monkeypatch.setattr(
        mqtt_publisher,
        "get_mqtt_config",
        lambda: {"host": "x", "port": 1883, "user": "u", "password": ""},
    )
    assert not mqtt_publisher.publish_health({"online": True})
    # Failure-streak moet ook bijgehouden zijn voor self-restart logica.
    assert mqtt_publisher.get_publish_failure_streak() >= 1
