#!/usr/bin/env python3
"""Finaliseer de onvolledige emsn-bats -> emsn-sonar rename.

Achtergrond: Tijdens de project-rename bleef ``~/emsn-bats/`` bestaan
als data-directory terwijl settings/DB al naar ``emsn-sonar`` wezen voor
sommige delen en ``emsn-bats`` voor anderen. Dit script:

1. Verplaatst recordings/spectrograms uit ``~/emsn-bats/`` naar
   ``~/emsn-sonar/`` (incremental - behoudt bestaande bestanden).
2. Update paden in ``bats.db`` detections + settings zodat alles verwijst
   naar ``emsn-sonar``.
3. Logt elke actie zodat rollback mogelijk blijft.

Gebruik:
    # Dry-run (standaard)
    python -m scripts.migration.finalize_emsn_bats_rename

    # Daadwerkelijk uitvoeren
    python -m scripts.migration.finalize_emsn_bats_rename --apply
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bats-rename")

HOME = Path.home()
OLD_ROOT = HOME / "emsn-bats"
NEW_ROOT = HOME / "emsn-sonar"
BATS_DB = NEW_ROOT / "data" / "bats.db"


def move_tree(src: Path, dst: Path, apply: bool) -> int:
    """Verplaats alle inhoud van src naar dst, incremental."""
    if not src.exists():
        log.info("Bron %s bestaat niet - overslaan", src)
        return 0

    moved = 0
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        target = dst / item.name
        if target.exists():
            log.debug("Bestaat al: %s - skip", target)
            continue
        if apply:
            shutil.move(str(item), str(target))
        moved += 1
        log.info("%s %s -> %s", "Verplaatst" if apply else "ZOU verplaatsen",
                 item, target)
    return moved


def update_db_paths(apply: bool) -> int:
    """Vervang /emsn-bats/ met /emsn-sonar/ in detections paden."""
    if not BATS_DB.exists():
        log.warning("bats.db niet gevonden op %s", BATS_DB)
        return 0

    conn = sqlite3.connect(str(BATS_DB), timeout=10)
    cur = conn.execute(
        "SELECT COUNT(*) FROM detections "
        "WHERE audio_path LIKE '%/emsn-bats/%' OR spectrogram_path LIKE '%/emsn-bats/%'"
    )
    count = cur.fetchone()[0]
    log.info("%d detecties met /emsn-bats/ in paden", count)

    if count and apply:
        conn.execute(
            "UPDATE detections SET "
            "audio_path = REPLACE(audio_path, '/emsn-bats/', '/emsn-sonar/'), "
            "spectrogram_path = REPLACE(spectrogram_path, '/emsn-bats/', '/emsn-sonar/') "
            "WHERE audio_path LIKE '%/emsn-bats/%' "
            "OR spectrogram_path LIKE '%/emsn-bats/%'"
        )
        # Settings bijwerken
        conn.execute(
            "UPDATE settings SET value = REPLACE(value, 'emsn-bats', 'emsn-sonar') "
            "WHERE value LIKE '%emsn-bats%'"
        )
        conn.commit()
        log.info("DB paden bijgewerkt")
    conn.close()
    return count


def remove_old_root_if_empty(apply: bool) -> None:
    """Verwijder ~/emsn-bats als het leeg is na de migratie."""
    if not OLD_ROOT.exists():
        return
    leftover = list(OLD_ROOT.rglob("*"))
    non_empty = [p for p in leftover if p.is_file()]
    if non_empty:
        log.warning("OUD %s bevat nog %d bestanden - niet verwijderd", OLD_ROOT, len(non_empty))
        return
    if apply:
        shutil.rmtree(OLD_ROOT)
        log.info("Lege %s verwijderd", OLD_ROOT)
    else:
        log.info("ZOU %s verwijderen (leeg)", OLD_ROOT)


def run(apply: bool) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    log.info("=== %s - finalize emsn-bats -> emsn-sonar rename ===", mode)

    move_tree(OLD_ROOT / "recordings", NEW_ROOT / "recordings", apply)
    move_tree(OLD_ROOT / "spectrograms", NEW_ROOT / "spectrograms", apply)
    update_db_paths(apply)
    remove_old_root_if_empty(apply)

    log.info("=== %s voltooid ===", mode)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Voer migratie daadwerkelijk uit")
    args = parser.parse_args()
    sys.exit(run(apply=args.apply))


if __name__ == "__main__":
    main()
