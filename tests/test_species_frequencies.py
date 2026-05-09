"""Tests voor species_frequencies lookup."""

from __future__ import annotations

import pytest

from scripts.core.species_frequencies import (
    SPECIES_FREQUENCY_BANDS,
    lookup_frequency_band,
)


def test_known_species_returns_band():
    band = lookup_frequency_band("Nyctalus leisleri")
    assert band is not None
    low, high = band
    assert 20_000 <= low <= 25_000
    assert 25_000 <= high <= 30_000


def test_unknown_species_returns_none():
    assert lookup_frequency_band("Mythicus imaginarius") is None


def test_empty_string_returns_none():
    assert lookup_frequency_band("") is None


def test_strips_whitespace():
    band1 = lookup_frequency_band("Nyctalus leisleri")
    band2 = lookup_frequency_band("  Nyctalus leisleri  ")
    assert band1 == band2


@pytest.mark.parametrize(
    "species,expect_below_30khz_peak",
    [
        ("Nyctalus leisleri", True),       # in probleem-zone
        ("Nyctalus noctula", True),        # in probleem-zone
        ("Eptesicus serotinus", True),     # peak ~27 kHz, in zone
        ("Pipistrellus pipistrellus", False),  # peak ~49 kHz
        ("Pipistrellus pygmaeus", False),
        ("Myotis daubentonii", False),
        ("Rhinolophus ferrumequinum", False),
    ],
)
def test_problem_zone_classification(species: str, expect_below_30khz_peak: bool):
    """Soorten met peak in 18-30 kHz zone moeten in dat bereik vallen."""
    band = lookup_frequency_band(species)
    assert band is not None
    low, high = band
    peak = (low + high) / 2
    if expect_below_30khz_peak:
        assert peak < 30_000, f"{species} peak {peak} should be <30kHz"
    else:
        assert peak >= 30_000, f"{species} peak {peak} should be >=30kHz"


def test_all_bands_have_low_lt_high():
    """Sanity: alle banden hebben low_freq < high_freq."""
    for species, (low, high) in SPECIES_FREQUENCY_BANDS.items():
        assert low < high, f"{species}: low={low} >= high={high}"


def test_all_bands_in_realistic_range():
    """Sanity: alle freqs liggen in 5 kHz - 200 kHz (Europese bats)."""
    for species, (low, high) in SPECIES_FREQUENCY_BANDS.items():
        assert 5_000 <= low <= 200_000, f"{species} low={low}"
        assert 5_000 <= high <= 200_000, f"{species} high={high}"
