"""Spectrogram generatie voor vleermuisdetecties."""

import logging
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


def generate_spectrogram(
    audio_path: str,
    output_path: str,
    sample_rate: int = 200000,
    fmin: int = 15000,
    fmax: int = 100000,
    figsize: tuple = (10, 4),
) -> str | None:
    """Genereer een spectrogram van een ultrasoon audiobestand.

    Returns het pad naar het spectrogram, of None bij fout.
    """
    try:
        import soundfile as sf

        audio, sr = sf.read(audio_path)
        if audio.ndim > 1:
            audio = audio[:, 0]

        fig, ax = plt.subplots(1, 1, figsize=figsize)
        ax.specgram(
            audio,
            Fs=sr,
            NFFT=1024,
            noverlap=512,
            cmap="magma",
            vmin=-120,
            vmax=-20,
        )
        ax.set_ylim(fmin, fmax)
        ax.set_ylabel("Frequentie (kHz)")
        ax.set_xlabel("Tijd (s)")

        # Y-as labels in kHz
        yticks = ax.get_yticks()
        ax.set_yticklabels([f"{int(y / 1000)}" for y in yticks])

        ax.set_facecolor("black")
        fig.patch.set_facecolor("black")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            output_path, bbox_inches="tight", dpi=100, facecolor="black"
        )
        plt.close(fig)
        return output_path
    except Exception:
        logger.exception("Spectrogram generatie mislukt voor %s", audio_path)
        return None


def generate_detection_spectrogram(
    audio_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    low_freq: float,
    high_freq: float,
    sample_rate: int = 200000,
    padding: float = 0.05,
) -> str | None:
    """Genereer spectrogram voor een specifieke detectie met markering."""
    try:
        import soundfile as sf

        audio, sr = sf.read(audio_path)
        if audio.ndim > 1:
            audio = audio[:, 0]

        fig, ax = plt.subplots(1, 1, figsize=(8, 4))
        ax.specgram(
            audio,
            Fs=sr,
            NFFT=1024,
            noverlap=512,
            cmap="magma",
            vmin=-120,
            vmax=-20,
        )

        # Markeer de detectie met een rechthoek
        from matplotlib.patches import Rectangle

        rect = Rectangle(
            (start_time - padding, low_freq - 1000),
            (end_time - start_time) + 2 * padding,
            (high_freq - low_freq) + 2000,
            linewidth=2,
            edgecolor="lime",
            facecolor="none",
        )
        ax.add_patch(rect)

        # Zoom naar relevant bereik
        margin = 0.2
        ax.set_xlim(
            max(0, start_time - margin),
            min(len(audio) / sr, end_time + margin),
        )
        ax.set_ylim(
            max(0, low_freq - 10000),
            min(sr / 2, high_freq + 10000),
        )

        ax.set_ylabel("Frequentie (kHz)")
        ax.set_xlabel("Tijd (s)")
        yticks = ax.get_yticks()
        ax.set_yticklabels([f"{int(y / 1000)}" for y in yticks])

        ax.set_facecolor("black")
        fig.patch.set_facecolor("black")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            output_path, bbox_inches="tight", dpi=100, facecolor="black"
        )
        plt.close(fig)
        return output_path
    except Exception:
        logger.exception(
            "Detectie spectrogram mislukt voor %s", audio_path
        )
        return None
