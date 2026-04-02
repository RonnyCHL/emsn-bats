# EMSN Bats - Vleermuismonitoring

Geautomatiseerde vleermuisdetectie en -classificatie voor het Ecologisch Monitoring Systeem Nijverdal (EMSN).

## Hardware

- **Raspberry Pi 5 8GB** - Debian Trixie 64-bit
- **Dodotronic Ultramic 200kHz** - USB ultrasone microfoon
- **Opslag:** NAS (192.168.1.25) via NFS/CIFS

## Software

- **BatDetect2** - Deep learning vleermuissoort-classificatie (macaodha/batdetect2)
- **Python 3.13** - Alle scripts
- **PostgreSQL** - Centrale database op NAS (port 5433)
- **MQTT** - Real-time detectie meldingen
- **Grafana** - Dashboard visualisatie

## Mappenstructuur

```
scripts/
  core/          - Gedeelde modules (config, database, logging)
  recording/     - Audio opname (Ultramic 200kHz)
  detection/     - BatDetect2 integratie en classificatie
  archive/       - Audio archivering naar NAS
  monitoring/    - Health checks en watchdog
config/          - Configuratie bestanden
systemd/         - Service en timer bestanden
database/
  migrations/    - SQL migratie bestanden
docs/
  samenvattingen/ - Sessie samenvattingen
```

## Nederlandse vleermuissoorten (BatDetect2)

| Soort | Wetenschappelijk | Echolocatie (kHz) |
|-------|-----------------|-------------------|
| Gewone dwergvleermuis | *Pipistrellus pipistrellus* | 45-50 |
| Ruige dwergvleermuis | *Pipistrellus nathusii* | 38-42 |
| Kleine dwergvleermuis | *Pipistrellus pygmaeus* | 53-58 |
| Laatvlieger | *Eptesicus serotinus* | 25-30 |
| Rosse vleermuis | *Nyctalus noctula* | 20-25 |
| Gewone grootoorvleermuis | *Plecotus auritus* | 45-50 |
| Watervleermuis | *Myotis daubentonii* | 45-50 |
| Franjestaart | *Myotis nattereri* | 45-50 |
| Meervleermuis | *Myotis dasycneme* | 35-40 |
| Baardvleermuis | *Myotis mystacinus* | 40-45 |

## Netwerk

- **Pi Bats (emsn-bats):** 192.168.1.88
- **NAS:** 192.168.1.25
- **MQTT Broker:** 192.168.1.178 (Pi Zolder)
- **Grafana:** http://192.168.1.25:3000

## Eigenaar

Ronny Hullegie - Ecologisch Monitoring Systeem Nijverdal
