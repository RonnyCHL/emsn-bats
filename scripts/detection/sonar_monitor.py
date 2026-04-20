"""Vleermuismonitor - continu opname en detectie met BatDetect2.

Neemt audio op in blokken, analyseert met BatDetect2, slaat detecties
op in SQLite en genereert spectrogrammen.
"""

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from scripts.core import systemd_notify

logger = logging.getLogger("sonar_monitor")


class SonarMonitor:
    """Hoofd monitoring loop: opname -> analyse -> opslag."""

    def __init__(self):
        self.running = False
        self._detector = None
        self._device_id = None

    def _get_config(self):
        """Lazy config laden."""
        from scripts.core.config import (
            get_config,
            get_config_bool,
            get_config_float,
            get_config_int,
        )

        return {
            "enabled": get_config_bool("recording.enabled"),
            "night_only": get_config_bool("recording.night_only"),
            "sample_rate": get_config_int("recording.sample_rate"),
            "duration": get_config_int("recording.duration_seconds"),
            "device_name": get_config("recording.device_name"),
            "threshold": get_config_float("detection.threshold"),
            "recordings_dir": get_config("storage.recordings_dir"),
            "spectrograms_dir": get_config("storage.spectrograms_dir"),
            "station": get_config("station.name"),
        }

    def _find_device(self, device_name: str) -> int | None:
        """Zoek Ultramic device ID."""
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if device_name in d["name"] and d["max_input_channels"] > 0:
                return i
        return None

    def _load_detector(self):
        """Lazy load BatDetect2 model."""
        if self._detector is None:
            logger.info("BatDetect2 model laden...")
            import batdetect2.api as api

            self._detector = api
            # Warm up
            config = api.get_config()
            logger.info(
                "BatDetect2 geladen: model=%s threshold=%.2f",
                config["model_name"],
                config["detection_threshold"],
            )
        return self._detector

    def _record_block(
        self, duration: int, sample_rate: int, device_id: int
    ) -> np.ndarray | None:
        """Neem een blok audio op."""
        try:
            audio = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                device=device_id,
                dtype="int16",
            )
            sd.wait()
            return audio.flatten()
        except Exception:
            logger.exception("Opname mislukt")
            return None

    def _save_audio(
        self, audio: np.ndarray, sample_rate: int, recordings_dir: str
    ) -> str:
        """Sla audio op als WAV bestand."""
        now = datetime.now()
        date_dir = Path(recordings_dir) / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        filename = f"bat_{now.strftime('%Y-%m-%d_%H-%M-%S')}.wav"
        filepath = date_dir / filename
        sf.write(str(filepath), audio, sample_rate)
        return str(filepath)

    def _analyze(
        self, audio_path: str, threshold: float
    ) -> list[dict]:
        """Analyseer audio met BatDetect2."""
        api = self._load_detector()
        config = api.get_config(detection_threshold=threshold)
        results = api.process_file(audio_path, config=config)

        annotations = results.get("pred_dict", {}).get("annotation", [])
        return [a for a in annotations if a.get("det_prob", 0) >= threshold]

    def _process_detections(
        self, detections: list[dict], audio_path: str, config: dict
    ):
        """Verwerk detecties: opslaan in DB + spectrogrammen."""
        from scripts.core.database import insert_detection
        from scripts.core.species import get_dutch_name
        from scripts.detection.spectrogram import (
            generate_detection_spectrogram,
        )

        audio_filename = Path(audio_path).name
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for det in detections:
            species = det.get("class", "Unknown")
            species_dutch = get_dutch_name(species)
            confidence = det.get("class_prob", 0)
            det_prob = det.get("det_prob", 0)
            low_freq = det.get("low_freq", 0)
            high_freq = det.get("high_freq", 0)
            start_time = det.get("start_time", 0)
            end_time = det.get("end_time", 0)
            duration_ms = (end_time - start_time) * 1000
            freq_peak = (low_freq + high_freq) / 2

            # Spectrogram
            spec_dir = Path(config["spectrograms_dir"])
            date_str = datetime.now().strftime("%Y-%m-%d")
            spec_filename = (
                f"{species.replace(' ', '_')}-"
                f"{int(confidence * 100)}-"
                f"{datetime.now().strftime('%H-%M-%S')}.png"
            )
            spec_path = spec_dir / date_str / spec_filename

            generated = generate_detection_spectrogram(
                audio_path=audio_path,
                output_path=str(spec_path),
                start_time=start_time,
                end_time=end_time,
                low_freq=low_freq,
                high_freq=high_freq,
                sample_rate=config["sample_rate"],
            )

            detection_record = {
                "detection_time": now_str,
                "species": species,
                "species_dutch": species_dutch,
                "confidence": confidence,
                "det_prob": det_prob,
                "frequency_low": low_freq,
                "frequency_high": high_freq,
                "frequency_peak": freq_peak,
                "duration_ms": duration_ms,
                "file_name": audio_filename,
                "audio_path": audio_path,
                "spectrogram_path": str(spec_path) if generated else None,
                "station": config["station"],
            }

            det_id = insert_detection(detection_record)
            logger.info(
                "Detectie #%d: %s (%s) confidence=%.2f freq=%d-%dHz",
                det_id,
                species_dutch,
                species,
                confidence,
                low_freq,
                high_freq,
            )

            # Publiceer naar MQTT
            try:
                from scripts.detection.mqtt_publisher import publish_detection

                publish_detection(detection_record)
            except Exception:
                logger.debug("MQTT publish overgeslagen")

    def run(self):
        """Start de monitoring loop."""
        from scripts.core.database import init_db
        from scripts.core.config import init_defaults

        # Initialiseer database en defaults
        init_db()
        init_defaults()

        config = self._get_config()

        # Zoek microfoon
        self._device_id = self._find_device(config["device_name"])
        if self._device_id is None:
            logger.error(
                "Ultramic niet gevonden! Zoek naar: %s",
                config["device_name"],
            )
            sys.exit(1)

        logger.info(
            "Bat Monitor gestart - device=%d sr=%d duration=%ds threshold=%.2f",
            self._device_id,
            config["sample_rate"],
            config["duration"],
            config["threshold"],
        )

        # Pre-load BatDetect2 model
        self._load_detector()

        self.running = True
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Signaal systemd dat we klaar zijn (Type=notify).
        systemd_notify.ready()
        systemd_notify.status("Monitoring actief")

        while self.running:
            try:
                # Watchdog heartbeat bovenaan elke iteratie: watchdog timeout
                # is 300s, typische cycle <10s dus ruime marge.
                systemd_notify.watchdog()

                # Herlaad config (kan via web UI gewijzigd zijn)
                config = self._get_config()

                if not config["enabled"]:
                    logger.debug("Opname uitgeschakeld, wacht 10s...")
                    time.sleep(10)
                    continue

                # Nacht-modus: alleen opnemen als het donker is
                if config["night_only"]:
                    from scripts.core.sun import is_night

                    if not is_night():
                        logger.debug("Dagmodus - wacht op zonsondergang...")
                        time.sleep(60)
                        continue

                # Opname
                audio = self._record_block(
                    config["duration"],
                    config["sample_rate"],
                    self._device_id,
                )
                if audio is None:
                    time.sleep(5)
                    continue

                # Check of er geluid is (skip stille blokken)
                rms = np.sqrt(np.mean(audio.astype(float) ** 2))
                if rms < 50:
                    logger.debug("Stil blok (RMS=%.1f), skip analyse", rms)
                    continue

                # Sla audio op
                audio_path = self._save_audio(
                    audio, config["sample_rate"], config["recordings_dir"]
                )

                # Analyseer
                detections = self._analyze(
                    audio_path, config["threshold"]
                )

                if detections:
                    logger.info(
                        "%d detectie(s) in %s",
                        len(detections),
                        Path(audio_path).name,
                    )
                    self._process_detections(detections, audio_path, config)
                else:
                    # Geen detecties: verwijder audio (bespaar schijfruimte)
                    Path(audio_path).unlink(missing_ok=True)

            except Exception:
                logger.exception("Fout in monitoring loop")
                time.sleep(10)

        systemd_notify.stopping()
        logger.info("Bat Monitor gestopt")

    def _signal_handler(self, signum, frame):
        """Graceful shutdown."""
        logger.info("Stop signaal ontvangen (%s)", signum)
        systemd_notify.status("Stoppen...")
        self.running = False


def main():
    """Entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                Path.home() / "emsn-sonar" / "logs" / "bat_monitor.log"
            ),
        ],
    )

    # Maak log directory
    log_dir = Path.home() / "emsn-sonar" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    monitor = SonarMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
