#!/usr/bin/env bash
# EMSN Sonar - Audio archief sync naar NAS
# Kopieert alle recordings naar NAS 8TB archief en houdt integriteit bij.
set -euo pipefail

readonly LOCAL_AUDIO="/home/ronny/emsn-sonar/recordings"
readonly LOCAL_SPEC="/home/ronny/emsn-sonar/spectrograms"
readonly NAS_AUDIO="/mnt/nas-birdnet-archive/sonar/audio"
readonly NAS_SPEC="/mnt/nas-birdnet-archive/sonar/spectrograms"
readonly LOG_FILE="/home/ronny/emsn-sonar/logs/audio_archive_sync.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

if ! mountpoint -q /mnt/nas-birdnet-archive; then
    log "ERROR: NAS archive niet gemount (/mnt/nas-birdnet-archive), sync overgeslagen"
    exit 1
fi

mkdir -p "$NAS_AUDIO" "$NAS_SPEC"

log "Audio sync start: $LOCAL_AUDIO -> $NAS_AUDIO"
rsync -a --info=stats1 \
    --exclude='*.tmp' \
    "$LOCAL_AUDIO/" "$NAS_AUDIO/" 2>&1 | tee -a "$LOG_FILE"

log "Spectrogrammen sync start: $LOCAL_SPEC -> $NAS_SPEC"
rsync -a --info=stats1 \
    "$LOCAL_SPEC/" "$NAS_SPEC/" 2>&1 | tee -a "$LOG_FILE"

log "Sync voltooid"
