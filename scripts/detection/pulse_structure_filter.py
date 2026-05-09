"""Pulsstructuur-filter voor BatDetect2 detecties.

Echte vleermuiscalls zijn korte FM-pulsen (5-15 ms) met ruime stilte
ertussen — binnen de gemeten frequentieband zit minimaal 20 dB verschil
tussen achtergrond en piek. Continue tonale bronnen (ultrasone repellers,
schakelende voedingen, harmonischen van LED-drivers) zenden permanent
in een smalle frequentieband en hebben slechts enkele dB dynamic range
omdat de "achtergrond" zelf het signaal is.

BatDetect2 classificeert die continue tonen ten onrechte als de soort
waarvan de frequentieband overlapt — vooral *Nyctalus leisleri*,
*Eptesicus serotinus* en *Nyctalus noctula* in de 18-26 kHz band.

Dit filter berekent de dynamic range van elke kandidaat-detectie binnen
zijn eigen gerapporteerde frequentieband (verhouding P99/P10 van de
band-energie envelope) en weigert detecties met te weinig contrast.

Geleerde context (mei 2026): 14.886 N. leisleri false positives in 14
dagen, allemaal P99/P10 < 20 in 22-26 kHz door een continue 24/25 kHz
bron in de buurt van de UltraMic. Echte calls hebben typisch P99/P10
> 200 (>23 dB).
"""

from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger("pulse_structure_filter")

DEFAULT_MIN_DYNAMIC_RANGE_DB = 15.0
DEFAULT_MAX_PEAK_FREQ_HZ = 30_000.0
DEFAULT_WINDOW_MS = 5.0
DEFAULT_HOP_MS = 2.5
MIN_BAND_HZ = 1000.0
_FLOOR_PERCENTILE = 10.0
_PEAK_PERCENTILE = 99.0
_EPSILON = 1e-30


def _band_energy_envelope(
    audio: np.ndarray,
    sample_rate: int,
    low_freq: float,
    high_freq: float,
    window_ms: float = DEFAULT_WINDOW_MS,
    hop_ms: float = DEFAULT_HOP_MS,
) -> np.ndarray:
    """Bereken de tijdsgewijze energie in een frequentieband.

    Vectorized STFT via stride-trick: alle frames in één rfft-call.
    Veel sneller dan een Python-loop over duizenden frames.

    Args:
        audio: Mono audio (int16 of float, willekeurige schaal).
        sample_rate: Sample rate in Hz.
        low_freq: Onderkant van de band in Hz.
        high_freq: Bovenkant van de band in Hz.
        window_ms: STFT-vensterduur in ms.
        hop_ms: STFT-hopgrootte in ms.

    Returns:
        1D-array van energieën (één per frame, willekeurige schaal).
        Lege array als de audio te kort is voor één volledig frame of
        de band buiten de Nyquist valt.
    """
    n_fft = max(8, int(sample_rate * window_ms / 1000.0))
    hop = max(1, int(sample_rate * hop_ms / 1000.0))

    if len(audio) < n_fft:
        return np.empty(0, dtype=np.float64)

    audio_f = audio.astype(np.float64, copy=False)
    window = np.hanning(n_fft)

    frames = np.lib.stride_tricks.sliding_window_view(audio_f, n_fft)[::hop]
    if frames.size == 0:
        return np.empty(0, dtype=np.float64)

    spec = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    band_mask = (freqs >= low_freq) & (freqs <= high_freq)

    if not band_mask.any():
        return np.empty(0, dtype=np.float64)

    return np.sum(spec[:, band_mask] ** 2, axis=1)


def compute_dynamic_range_db(
    audio: np.ndarray,
    sample_rate: int,
    low_freq: float,
    high_freq: float,
    window_ms: float = DEFAULT_WINDOW_MS,
    hop_ms: float = DEFAULT_HOP_MS,
) -> float:
    """Bereken de dynamic range van een frequentieband over de hele opname.

    Definitie: ``10 * log10(P99 / P10)`` van de STFT-band-energie. Hoge
    waarde (>20 dB) duidt op gepulseerde signalen waar duidelijk verschil
    is tussen stilte en piek; lage waarde (<15 dB) op een continue bron
    waar achtergrond bijna gelijk is aan het signaal.

    Args:
        audio: Mono audio.
        sample_rate: Sample rate in Hz.
        low_freq: Onderkant band in Hz.
        high_freq: Bovenkant band in Hz.
        window_ms: STFT-vensterduur.
        hop_ms: STFT-hopgrootte.

    Returns:
        Dynamic range in dB. Geeft 0.0 terug bij te weinig audio of een
        lege band.
    """
    band_min = max(0.0, min(low_freq, high_freq))
    band_max = min(sample_rate / 2.0, max(low_freq, high_freq))

    if band_max - band_min < MIN_BAND_HZ:
        midpoint = (band_min + band_max) / 2.0
        band_min = max(0.0, midpoint - MIN_BAND_HZ / 2.0)
        band_max = min(sample_rate / 2.0, midpoint + MIN_BAND_HZ / 2.0)

    envelope = _band_energy_envelope(
        audio,
        sample_rate,
        band_min,
        band_max,
        window_ms=window_ms,
        hop_ms=hop_ms,
    )
    if envelope.size < 2:
        return 0.0

    floor = max(float(np.percentile(envelope, _FLOOR_PERCENTILE)), _EPSILON)
    peak = max(float(np.percentile(envelope, _PEAK_PERCENTILE)), _EPSILON)

    return 10.0 * math.log10(peak / floor)


def filter_detections(
    audio: np.ndarray,
    sample_rate: int,
    detections: list[dict],
    min_dynamic_range_db: float = DEFAULT_MIN_DYNAMIC_RANGE_DB,
    max_peak_freq_hz: float = DEFAULT_MAX_PEAK_FREQ_HZ,
) -> tuple[list[dict], list[dict]]:
    """Splits BatDetect2 detecties in echte pulsen vs continue tonen.

    Het filter wordt alleen toegepast op detecties waarvan de peak-
    frequentie onder ``max_peak_freq_hz`` ligt — dat is de zone (18-30
    kHz) waarin de bekende tonale interferentiebron actief is. Detecties
    erboven (Pipistrellus 45-55 kHz, Myotis, Plecotus) zouden onnodig
    gefilterd worden door de DR-metric en blijven daarom altijd behouden.

    Voor detecties in de probleem-zone wordt de dynamic range berekend
    binnen hun eigen gerapporteerde frequentieband. Detecties met te
    weinig contrast tussen achtergrond en piek worden afgewezen als
    tonal-artifact.

    Args:
        audio: Volledige opname (mono).
        sample_rate: Sample rate in Hz.
        detections: BatDetect2-output annotaties (dicts met
            ``low_freq`` en ``high_freq``).
        min_dynamic_range_db: Detecties met minder dynamic range worden
            afgewezen (default 15 dB).
        max_peak_freq_hz: Filter wordt alleen toegepast op detecties
            met peak-frequentie onder deze grens (default 30 kHz).

    Returns:
        Tuple ``(kept, rejected)``. Elke detectie krijgt een nieuwe
        sleutel ``dynamic_range_db``. Afgewezen detecties krijgen extra
        ``reject_reason='tonal_artifact'``.
    """
    kept: list[dict] = []
    rejected: list[dict] = []

    for det in detections:
        low_freq = float(det.get("low_freq", 0) or 0)
        high_freq = float(det.get("high_freq", 0) or 0)
        peak_freq = (low_freq + high_freq) / 2.0

        if peak_freq >= max_peak_freq_hz:
            det["dynamic_range_db"] = None
            kept.append(det)
            continue

        dr_db = compute_dynamic_range_db(
            audio, sample_rate, low_freq, high_freq
        )
        det["dynamic_range_db"] = dr_db

        if dr_db < min_dynamic_range_db:
            det["reject_reason"] = "tonal_artifact"
            rejected.append(det)
        else:
            kept.append(det)

    if rejected:
        logger.info(
            "Pulsfilter: %d/%d detecties afgewezen als tonal_artifact "
            "(min_dr=%.1f dB, laagste rejected=%.1f dB)",
            len(rejected),
            len(detections),
            min_dynamic_range_db,
            min(d["dynamic_range_db"] for d in rejected),
        )

    return kept, rejected
