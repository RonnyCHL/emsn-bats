"""Database concurrency-tests.

Worst-case scenario verifiëren: sonar_monitor schrijft gulzig terwijl
stats_publisher en de web UI lezen. Met SQLite + WAL hoort dat
foutloos te kunnen, maar default journal_mode + busy_timeout=0 geeft
``database is locked`` errors. Test borgt dat de productie-config
(WAL + busy_timeout) bestand is tegen reële load.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest


_WRITER_ROUNDS = 200
_READER_ROUNDS = 400
_BUSY_TIMEOUT_MS = 5000


def _open(db: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open een connectie met dezelfde pragma's als productie."""
    if readonly:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    else:
        conn = sqlite3.connect(db, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


def _writer(db: Path, errors: list[Exception]) -> None:
    try:
        conn = _open(db)
        try:
            for i in range(_WRITER_ROUNDS):
                conn.execute(
                    "INSERT INTO detections "
                    "(detection_time, species, confidence) VALUES (?, ?, ?)",
                    (f"2026-04-25 20:00:{i % 60:02d}", "Test bat", 0.5),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        errors.append(exc)


def _reader(db: Path, errors: list[Exception]) -> None:
    try:
        conn = _open(db, readonly=True)
        try:
            for _ in range(_READER_ROUNDS):
                conn.execute("SELECT COUNT(*) FROM detections").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        errors.append(exc)


def test_concurrent_writers_and_readers_dont_deadlock(empty_bats_db: Path) -> None:
    """Meerdere gelijktijdige writers + readers mogen geen lock-error geven."""
    # Forceer WAL eenmalig (anders blijft DB in delete-mode tot eerste open).
    init = _open(empty_bats_db)
    init.close()

    errors: list[Exception] = []
    threads = [
        threading.Thread(target=_writer, args=(empty_bats_db, errors)),
        threading.Thread(target=_writer, args=(empty_bats_db, errors)),
        threading.Thread(target=_reader, args=(empty_bats_db, errors)),
        threading.Thread(target=_reader, args=(empty_bats_db, errors)),
    ]

    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - start

    assert all(not t.is_alive() for t in threads), (
        f"Thread bleef hangen na 30s - mogelijk deadlock (elapsed={elapsed:.1f}s)"
    )
    assert not errors, f"Concurrency-fouten: {errors!r}"

    # Verifieer dat beide writers hun beloofde rijen hebben gecommit.
    final = _open(empty_bats_db, readonly=True)
    try:
        (count,) = final.execute("SELECT COUNT(*) FROM detections").fetchone()
    finally:
        final.close()
    assert count == 2 * _WRITER_ROUNDS


def test_wal_mode_actually_active(empty_bats_db: Path) -> None:
    """Sanity check dat WAL aan blijft staan (PRAGMA is per-connectie maar
    journal_mode is een persistent attribuut van de database file)."""
    conn = _open(empty_bats_db)
    try:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    finally:
        conn.close()
    assert mode.lower() == "wal", f"Verwacht WAL mode, kreeg {mode}"
