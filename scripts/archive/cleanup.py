"""Cleanup service - verwijdert oude audio en spectrogrammen.

Respecteert de retention_days instelling uit de configuratie.
Behoudt audio bestanden die bij detecties horen langer.
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.core.config import get_config_int
from scripts.core.database import get_connection, init_db

logger = logging.getLogger("bat_cleanup")


def cleanup_old_files() -> dict[str, int]:
    """Verwijder bestanden ouder dan retention periode.

    Returns:
        Dict met counts per type (audio_removed, spec_removed, dirs_removed).
    """
    retention_days = get_config_int("storage.retention_days")
    cutoff = datetime.now() - timedelta(days=retention_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    stats = {"audio_removed": 0, "spec_removed": 0, "dirs_removed": 0}

    # Audio bestanden zonder detectie
    recordings_dir = Path(get_config_int.__module__).parent.parent / "recordings"
    # Gebruik config pad
    from scripts.core.config import get_config

    recordings_dir = Path(get_config("storage.recordings_dir"))
    spectrograms_dir = Path(get_config("storage.spectrograms_dir"))

    conn = get_connection()

    # Verwijder oude datummappen
    for base_dir, stat_key in [
        (recordings_dir, "audio_removed"),
        (spectrograms_dir, "spec_removed"),
    ]:
        if not base_dir.exists():
            continue

        for date_dir in sorted(base_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            # Directory naam is YYYY-MM-DD
            dir_date = date_dir.name
            if dir_date >= cutoff_str:
                continue

            # Check of er detecties zijn die deze bestanden refereren
            if stat_key == "audio_removed":
                # Bewaar audio bestanden die bij detecties horen
                for audio_file in date_dir.glob("*.wav"):
                    has_detection = conn.execute(
                        "SELECT 1 FROM detections WHERE audio_path = ? LIMIT 1",
                        (str(audio_file),),
                    ).fetchone()

                    if has_detection:
                        logger.debug("Bewaard (heeft detectie): %s", audio_file.name)
                    else:
                        audio_file.unlink()
                        stats[stat_key] += 1
            else:
                # Spectrogrammen: verwijder hele map
                for f in date_dir.iterdir():
                    f.unlink()
                    stats[stat_key] += 1

            # Verwijder lege mappen
            if date_dir.exists() and not any(date_dir.iterdir()):
                date_dir.rmdir()
                stats["dirs_removed"] += 1

    return stats


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    init_db()
    stats = cleanup_old_files()
    logger.info(
        "Cleanup voltooid: %d audio, %d spectrogrammen, %d mappen verwijderd",
        stats["audio_removed"],
        stats["spec_removed"],
        stats["dirs_removed"],
    )


if __name__ == "__main__":
    main()
