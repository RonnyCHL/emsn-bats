#!/usr/bin/env bash
# EMSN Sonar - Root filesystem rsync backup naar NAS
# Draait elke nacht, exclude-list houdt backup compact.
set -euo pipefail

readonly STATION="sonar"
readonly NAS_BASE="/mnt/nas-birdnet-archive/sd-backups/${STATION}/rsync"
readonly LOG_FILE="/home/ronny/emsn-sonar/logs/sd_backup_rsync.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

if ! mountpoint -q /mnt/nas-birdnet-archive; then
    log "ERROR: NAS archive niet gemount, backup overgeslagen"
    exit 1
fi

mkdir -p "$NAS_BASE"

log "Start rsync backup naar $NAS_BASE"

rsync -aAX --delete --info=stats1 \
    --exclude='/dev/*' \
    --exclude='/proc/*' \
    --exclude='/sys/*' \
    --exclude='/tmp/*' \
    --exclude='/run/*' \
    --exclude='/mnt/*' \
    --exclude='/media/*' \
    --exclude='/lost+found' \
    --exclude='/var/cache/apt/archives/*.deb' \
    --exclude='/var/log/journal/*' \
    --exclude='/home/ronny/emsn-sonar/recordings' \
    --exclude='/home/ronny/emsn-sonar/spectrograms' \
    --exclude='/home/ronny/emsn-sonar/venv' \
    --exclude='/home/ronny/BattyBirdNET-Analyzer/venv' \
    --exclude='/home/ronny/.cache' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    / "$NAS_BASE/" 2>&1 | tee -a "$LOG_FILE"

log "Backup voltooid"
