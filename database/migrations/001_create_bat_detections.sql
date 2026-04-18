-- Migratie: bat_detections tabel
-- Datum: 2026-04-02

CREATE TABLE IF NOT EXISTS bat_detections (
    id SERIAL PRIMARY KEY,
    station VARCHAR(50) NOT NULL DEFAULT 'emsn-sonar',
    detection_timestamp TIMESTAMPTZ NOT NULL,
    species VARCHAR(100),
    species_dutch VARCHAR(100),
    confidence REAL,
    frequency_peak REAL,          -- Piek frequentie in Hz
    frequency_low REAL,           -- Laagste frequentie in Hz
    frequency_high REAL,          -- Hoogste frequentie in Hz
    duration_ms REAL,             -- Duur van de roep in ms
    file_name VARCHAR(255),
    audio_path VARCHAR(500),
    spectrogram_path VARCHAR(500),
    audio_checksum VARCHAR(64),
    audio_archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexen
CREATE INDEX IF NOT EXISTS idx_bat_detections_timestamp ON bat_detections (detection_timestamp);
CREATE INDEX IF NOT EXISTS idx_bat_detections_species ON bat_detections (species);
CREATE INDEX IF NOT EXISTS idx_bat_detections_station ON bat_detections (station);

-- Commentaar
COMMENT ON TABLE bat_detections IS 'Vleermuisdetecties via BatDetect2 + Dodotronic Ultramic 200kHz';
