"""Time-stretch: maak ultrasone vleermuisgeluiden hoorbaar.

Verlaagt de sample rate zodat echolocatiepulsen (20-100 kHz)
verschuiven naar het hoorbare bereik (1-5 kHz).
Standaard factor 10x: 50 kHz -> 5 kHz.
"""

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Standaard stretch factor: 10x vertraging
# 200kHz opname -> 20kHz playback -> alles 10x lager in frequentie
DEFAULT_FACTOR = 10
TARGET_SAMPLE_RATE = 22050  # CD-kwaliteit voor playback


def time_stretch(
    input_path: str,
    output_path: str | None = None,
    factor: int = DEFAULT_FACTOR,
) -> str | None:
    """Converteer ultrasoon audio naar hoorbaar bereik.

    Args:
        input_path: Pad naar ultrasone WAV (200kHz sample rate)
        output_path: Pad voor output WAV. Als None, wordt automatisch bepaald.
        factor: Vertraging factor (10 = 50kHz -> 5kHz)

    Returns:
        Pad naar hoorbare WAV, of None bij fout.
    """
    try:
        audio, sr = sf.read(input_path)
        if audio.ndim > 1:
            audio = audio[:, 0]

        # Nieuwe sample rate = origineel / factor
        # Bijv: 200000 / 10 = 20000 Hz
        # Audio wordt factor x zo lang, frequenties factor x zo laag
        new_sr = sr // factor

        # Resample naar standaard playback rate als het te laag is
        if new_sr < TARGET_SAMPLE_RATE:
            # Upsample met lineaire interpolatie
            duration = len(audio) / new_sr
            target_samples = int(duration * TARGET_SAMPLE_RATE)
            x_old = np.linspace(0, 1, len(audio))
            x_new = np.linspace(0, 1, target_samples)
            audio = np.interp(x_new, x_old, audio)
            new_sr = TARGET_SAMPLE_RATE

        if output_path is None:
            p = Path(input_path)
            output_path = str(p.parent / f"{p.stem}_audible.wav")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, audio, new_sr)

        logger.debug(
            "Time-stretch: %s -> %s (factor=%d, sr=%d->%d)",
            Path(input_path).name,
            Path(output_path).name,
            factor,
            sr,
            new_sr,
        )
        return output_path

    except Exception:
        logger.exception("Time-stretch mislukt voor %s", input_path)
        return None
