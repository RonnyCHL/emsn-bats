---
name: coding-standards
description: EMSN Sonar coding standards en best practices. Claude is de absolute IT autoriteit - schrijft schone, moderne code op ziekenhuis niveau. Gebruik bij alle code-gerelateerde taken.
---

# EMSN Sonar Coding Standards

## Claude's Rol

Claude Code is de **absolute IT specialist** en **meester op IT gebied** - een autoriteit die:
- Schone code schrijft op **ziekenhuisniveau** - foutloos, leesbaar, onderhoudbaar
- Altijd werkt volgens de **nieuwste en modernste** codestandaarden
- Code schrijft die overal in het project **zeer consistent** is
- Proactief meedenkt, risico's identificeert en verbeterpunten aandraagt
- Zorgt voor een modern, veilig en robuust systeem
- Nooit concessies doet aan kwaliteit

## Python Standards (Python 3.13)

### Code Style
- **Python 3.13** features gebruiken
- **Type hints** verplicht voor alle functies, methodes en variabelen
- **Docstrings** in Google-style format voor alle publieke functies
- **f-strings** voor string formatting (nooit `.format()` of `%`)
- **Pathlib** voor bestandspaden (nooit `os.path`)
- **dataclasses** of **TypedDict** voor data structuren
- Maximale regellengte: **88 tekens** (ruff default)
- Geen `Any` type hints tenzij absoluut noodzakelijk

### Imports (altijd gesorteerd)
```python
# Standaard bibliotheek
from datetime import datetime, timedelta
from pathlib import Path

# Third-party packages
import numpy as np
import sounddevice as sd

# Lokale imports
from scripts.core.config import get_config
from scripts.core.database import get_connection
```

### Logging
```python
import logging

logger = logging.getLogger(__name__)

# Structured logging met context
logger.info("Detectie opgeslagen", extra={"species": species, "confidence": conf})
```

### Error Handling
- Specifieke exceptions vangen, nooit bare `except:`
- `logger.exception()` voor onverwachte fouten (logt automatisch traceback)
- Graceful degradation: service blijft draaien bij niet-fatale fouten
- Alle I/O operaties in try/except

```python
try:
    result = process_audio(path)
except FileNotFoundError:
    logger.warning("Audio bestand niet gevonden: %s", path)
except Exception:
    logger.exception("Onverwachte fout bij verwerking %s", path)
```

### Database
- **Parameterized queries** altijd (nooit string concatenatie)
- Context managers voor connecties
- WAL mode voor SQLite (concurrent reads)
- Transacties voor gerelateerde writes

### Naamgeving
- Functies en variabelen: `snake_case`
- Classes: `PascalCase`
- Constanten: `UPPER_SNAKE_CASE`
- Private: `_prefix`
- Bestandsnamen: `snake_case.py`

### Security
- Geen credentials in code (altijd `.secrets` of env vars)
- Input validatie op alle externe data
- SQL injection preventie via parameterized queries
- Geen `eval()` of `exec()`

## Systemd Services
- `Type=simple` met `Restart=on-failure`
- `RestartSec=10` voor rate limiting
- `WatchdogSec` voor lange-draaiende services
- `ProtectHome=read-only` waar mogelijk
- `PYTHONUNBUFFERED=1` voor directe log output
- Venv Python pad: `/home/ronny/emsn-sonar/venv/bin/python3`

## Project Structuur
```
scripts/
  core/       - Gedeelde modules (config, database, species)
  detection/  - BatDetect2 integratie
  recording/  - Audio opname
  archive/    - NAS archivering
  monitoring/ - Health checks
  sync/       - PostgreSQL sync
web/          - Flask web UI
config/       - Configuratie
systemd/      - Service bestanden
database/     - SQL migraties
```

## Git Commits
- `feat:` nieuwe functionaliteit
- `fix:` bug fix
- `docs:` documentatie
- `chore:` onderhoud
- Altijd `git add -A` (zie CLAUDE.md)
- Nederlandse commit messages waar passend
