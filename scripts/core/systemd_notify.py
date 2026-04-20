"""Systemd notify helper voor sonar services.

Wrapt `systemd.daemon.notify` zodat services veilig sd_notify kunnen sturen
zonder crash als het package ontbreekt. Als `systemd` niet is geïnstalleerd
zijn de calls no-ops zodat de service buiten systemd ook blijft draaien.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from systemd import daemon as _sd_daemon  # type: ignore[import-not-found]

    _AVAILABLE = True
except ImportError:
    _sd_daemon = None
    _AVAILABLE = False
    logger.warning(
        "systemd.daemon niet beschikbaar - sd_notify is no-op. "
        "Installeer 'systemd-python' en 'libsystemd-dev' als WatchdogSec actief is."
    )


def is_available() -> bool:
    """Geeft True als sd_notify calls daadwerkelijk iets doen."""
    return _AVAILABLE


def ready() -> None:
    """Signaleer systemd dat de service klaar is (Type=notify)."""
    if _sd_daemon is not None:
        _sd_daemon.notify("READY=1")


def watchdog() -> None:
    """Stuur een watchdog heartbeat naar systemd."""
    if _sd_daemon is not None:
        _sd_daemon.notify("WATCHDOG=1")


def status(message: str) -> None:
    """Werk de statusregel van de service bij (zichtbaar in systemctl status)."""
    if _sd_daemon is not None:
        _sd_daemon.notify(f"STATUS={message}")


def stopping() -> None:
    """Signaleer systemd dat de service bezig is te stoppen."""
    if _sd_daemon is not None:
        _sd_daemon.notify("STOPPING=1")
