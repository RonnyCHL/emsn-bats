# EMSN Sonar - Instructies voor Claude Code

## Rol
Claude Code is de **absolute IT specialist** voor dit project.

## Project
Vleermuismonitoring met BatDetect2 + Dodotronic Ultramic 200kHz op Raspberry Pi 5.
Onderdeel van EMSN (Ecologisch Monitoring Systeem Nijverdal).
Eigenaar: Ronny Hullegie

## Gouden Regels
- Stap voor stap werken, elke fase testen
- **GEEN EIGEN AANNAMES** - Bij twijfel altijd vragen wat Ronny wil
- Volg afspraken exact op, verzin geen alternatieven
- Altijd backups maken voor destructieve acties

## Git Commit Protocol
1. `git status` - Controleer ALLE gewijzigde bestanden
2. `git diff` - Review ALLE wijzigingen
3. **ALTIJD** `git add -A` gebruiken
4. Na commit: `git show --stat HEAD` om te verifieren

## Werkwijze
- Start sessie: lees eerst /docs/ voor huidige status
- Einde sessie: samenvatting opslaan in /docs/samenvattingen/
- Daarna committen en pushen naar GitHub
- Documentatie in het Nederlands

## Credentials
**Alle credentials staan in `.secrets` (niet in git!)**

## Hardware
- **Pi:** Raspberry Pi 5 8GB, Debian Trixie 64-bit
- **Microfoon:** Dodotronic Ultramic 200kHz (USB audio device)
- **Opslag:** NAS 8TB USB via NFS

## Software Stack
- **BatDetect2** (macaodha/batdetect2) - Vleermuissoort-classificatie
- **Python 3.13** met venv
- **PostgreSQL** op NAS (192.168.1.25:5433, database: emsn)
- **MQTT** broker op Zolder (192.168.1.178:1883)

## Netwerk
- **Pi Bats (emsn-sonar):** 192.168.1.88
- **NAS (DS224Plus):** 192.168.1.25
- **MQTT Broker (Zolder):** 192.168.1.178:1883
- **Grafana:** http://192.168.1.25:3000

## Database
- Tabel: `bat_detections` in PostgreSQL database `emsn`
- Grafana dashboard: emsn-sonar-monitoring (al voorbereid)

## MQTT Topics
- `emsn2/bats/detection` - Live vleermuisdetecties
- `emsn2/bats/stats` - Statistieken
- `emsn2/bats/health` - Health status

## Mappenstructuur
- /scripts/core/ - Gedeelde modules
- /scripts/recording/ - Audio opname
- /scripts/detection/ - BatDetect2 classificatie
- /scripts/archive/ - Archivering naar NAS
- /scripts/monitoring/ - Health checks
- /config/ - Configuratie
- /systemd/ - Service bestanden
- /database/migrations/ - SQL migraties
- /docs/ - Documentatie
- /docs/samenvattingen/ - Sessie samenvattingen

## Commit Stijl
- feat: nieuwe functionaliteit
- fix: bug fix
- docs: documentatie update
- chore: opruimen/onderhoud

## Bekende issues

### MQTT publisher (opgelost 2026-04-25)
Twee processen (sonar-monitor + sonar-bavaria) gebruikten dezelfde
hardcoded client_id en de `_get_client()` recreate-pad lekte threads
en sockets bij elke disconnect. Resultaat na 3 dagen: 1004 sockets,
507 threads, FD-limit (1024) bereikt → ALSA `Illegal combination of
I/O devices` → opname stopt → 0 detecties. Fix in `mqtt_publisher.py`:
unieke client_id per proces (rol+pid+host), persistente singleton,
paho's interne `reconnect_delay_set()`. Plus FD self-check in
`sonar_monitor.py` die het proces afbreekt bij ≥80% van rlimit zodat
systemd herstart i.p.v. stilletjes door te modderen.

### BattyBirdNET-Bavaria analyzer (open, upstream)
`bat_ident.py --area Bavaria` faalt op alle WAVs met
`ValueError: Tensor data is null. Run allocate_tensors() first` in
`ai-edge-litert` 2.1.4. Bekend probleem met TFLite singleton
INTERPRETER + custom classifier. Sinds 18 april 2026 geen enkele
Bavaria detectie verwerkt. Fix vereist upgrade/patch van
BattyBirdNET-Analyzer (third-party), buiten scope van emsn-sonar zelf.
Workaround: BatDetect2 doet primaire detectie en werkt prima.
