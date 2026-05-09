"""Typische echolocatie-frequentiebanden per Europese vleermuissoort.

Gebruikt door classifiers die wel een soortnaam teruggeven maar GEEN
frequentie-info in hun output (zoals BattyBirdNET-Bavaria). De lookup
levert ``(low_freq_hz, high_freq_hz)`` zodat we frequentie-gevoelige
nabewerking (bv. pulsstructuur-filter) ook op die detecties kunnen
toepassen.

Bandbreedtes komen uit:
1. BatDetect2-output statistieken op onze eigen 14 dagen sample (bekend
   correct gerangeerde detecties).
2. Field-guide referenties voor Europese soorten (Dietz & Kiefer,
   Bats of Britain and Europe).

Bij twijfel kiezen we de RUIME band (typische min - typische max van
de FM-down-sweep), niet alleen de piek. Dat past bij wat BatDetect2
intern als ``low_freq``/``high_freq`` rapporteert: niet 'peak' maar
'detectie-band'.

Onbekende soorten geven ``None`` terug; aanroepers zouden dan moeten
besluiten het filter over te slaan i.p.v. te raden.
"""

from __future__ import annotations

# Mapping van scientific name -> (low_freq_hz, high_freq_hz).
# Ranges zijn de typische FM-sweep + ruime marge voor individuele variatie.
SPECIES_FREQUENCY_BANDS: dict[str, tuple[float, float]] = {
    # Lage soorten (peak <30 kHz) — gevoelig voor 24/25 kHz interferentie
    "Nyctalus leisleri": (21_000.0, 27_000.0),       # peak ~24 kHz
    "Nyctalus noctula": (17_000.0, 24_000.0),        # peak ~20 kHz
    "Eptesicus serotinus": (22_000.0, 35_000.0),     # peak ~27 kHz
    "Eptesicus nilssonii": (25_000.0, 35_000.0),     # peak ~29 kHz
    "Vespertilio murinus": (20_000.0, 28_000.0),     # peak ~24 kHz
    "Tadarida teniotis": (10_000.0, 20_000.0),       # peak ~12 kHz
    # Middel-hoog (peak 30-45 kHz)
    "Barbastellus barbastellus": (28_000.0, 42_000.0),  # dual call
    "Pipistrellus nathusii": (35_000.0, 50_000.0),      # peak ~39 kHz
    "Pipistrellus kuhlii": (35_000.0, 45_000.0),        # peak ~38 kHz
    "Plecotus auritus": (28_000.0, 50_000.0),           # brede band
    "Plecotus austriacus": (28_000.0, 50_000.0),
    "Plecotus macrobullaris": (28_000.0, 50_000.0),
    "Myotis dasycneme": (25_000.0, 40_000.0),
    "Myotis myotis": (25_000.0, 45_000.0),
    "Myotis bechsteinii": (35_000.0, 90_000.0),
    "Myotis emarginatus": (40_000.0, 100_000.0),
    # Hoge soorten (peak >45 kHz) — vallen sowieso buiten cutoff van
    # 30 kHz. Behouden in de tabel voor compleetheid van rapportage.
    "Pipistrellus pipistrellus": (42_000.0, 55_000.0),  # peak ~49 kHz
    "Pipistrellus pygmaeus": (52_000.0, 65_000.0),      # peak ~58 kHz
    "Myotis daubentonii": (35_000.0, 70_000.0),
    "Myotis mystacinus": (35_000.0, 90_000.0),
    "Myotis brandtii": (35_000.0, 90_000.0),
    "Myotis alcathoe": (40_000.0, 100_000.0),
    "Myotis nattereri": (30_000.0, 100_000.0),
    "Miniopterus schreibersii": (45_000.0, 60_000.0),
    "Hypsugo savii": (32_000.0, 42_000.0),
    # Hoefijzerneuzen: zeer scherpe constant-frequency call
    "Rhinolophus ferrumequinum": (78_000.0, 84_000.0),  # ~81 kHz CF
    "Rhinolophus hipposideros": (105_000.0, 115_000.0), # ~110 kHz CF
    "Rhinolophus euryale": (100_000.0, 108_000.0),
    "Rhinolophus mehelyi": (102_000.0, 110_000.0),
    "Rhinolophus blasii": (90_000.0, 100_000.0),
}


def lookup_frequency_band(scientific_name: str) -> tuple[float, float] | None:
    """Geef ``(low_freq_hz, high_freq_hz)`` voor een soort, of ``None``.

    Args:
        scientific_name: Wetenschappelijke naam zoals geleverd door de
            classifier (bv. ``"Nyctalus leisleri"``).

    Returns:
        Tuple met de FM-sweep ondergrens en bovengrens in Hz, of
        ``None`` als de soort niet in de tabel staat.
    """
    if not scientific_name:
        return None
    return SPECIES_FREQUENCY_BANDS.get(scientific_name.strip())
