"""Nederlandse vleermuissoorten mapping voor BatDetect2."""

# BatDetect2 wetenschappelijke naam -> Nederlandse naam
SPECIES_DUTCH = {
    "Barbastella barbastellus": "Mopsvleermuis",
    "Eptesicus serotinus": "Laatvlieger",
    "Myotis alcathoe": "Alcathoe's vleermuis",
    "Myotis bechsteinii": "Bechsteins vleermuis",
    "Myotis brandtii": "Brandts vleermuis",
    "Myotis dasycneme": "Meervleermuis",
    "Myotis daubentonii": "Watervleermuis",
    "Myotis emarginatus": "Ingekorven vleermuis",
    "Myotis myotis": "Vale vleermuis",
    "Myotis mystacinus": "Baardvleermuis",
    "Myotis nattereri": "Franjestaart",
    "Nyctalus leisleri": "Bosvleermuis",
    "Nyctalus noctula": "Rosse vleermuis",
    "Pipistrellus kuhlii": "Kuhls dwergvleermuis",
    "Pipistrellus nathusii": "Ruige dwergvleermuis",
    "Pipistrellus pipistrellus": "Gewone dwergvleermuis",
    "Pipistrellus pygmaeus": "Kleine dwergvleermuis",
    "Plecotus auritus": "Gewone grootoorvleermuis",
    "Plecotus austriacus": "Grijze grootoorvleermuis",
    "Rhinolophus ferrumequinum": "Grote hoefijzerneus",
    "Rhinolophus hipposideros": "Kleine hoefijzerneus",
    "Vespertilio murinus": "Tweekleurige vleermuis",
}

# Typische echolocatie frequenties (piek kHz)
SPECIES_FREQUENCY = {
    "Barbastella barbastellus": 33,
    "Eptesicus serotinus": 27,
    "Myotis alcathoe": 50,
    "Myotis bechsteinii": 45,
    "Myotis brandtii": 42,
    "Myotis dasycneme": 37,
    "Myotis daubentonii": 47,
    "Myotis emarginatus": 52,
    "Myotis myotis": 33,
    "Myotis mystacinus": 43,
    "Myotis nattereri": 47,
    "Nyctalus leisleri": 26,
    "Nyctalus noctula": 22,
    "Pipistrellus kuhlii": 40,
    "Pipistrellus nathusii": 40,
    "Pipistrellus pipistrellus": 47,
    "Pipistrellus pygmaeus": 55,
    "Plecotus auritus": 47,
    "Plecotus austriacus": 30,
    "Rhinolophus ferrumequinum": 82,
    "Rhinolophus hipposideros": 110,
    "Vespertilio murinus": 25,
}

# Zeldzaamheid in Nederland (1=algemeen, 5=zeer zeldzaam)
SPECIES_RARITY_NL = {
    "Pipistrellus pipistrellus": 1,     # Zeer algemeen
    "Pipistrellus nathusii": 2,         # Vrij algemeen
    "Pipistrellus pygmaeus": 2,
    "Eptesicus serotinus": 2,
    "Nyctalus noctula": 2,
    "Myotis daubentonii": 2,
    "Plecotus auritus": 2,
    "Nyctalus leisleri": 3,
    "Myotis nattereri": 3,
    "Myotis mystacinus": 3,
    "Myotis brandtii": 3,
    "Myotis dasycneme": 3,              # Rode Lijst
    "Barbastella barbastellus": 4,       # Zeer zeldzaam
    "Plecotus austriacus": 4,
    "Myotis bechsteinii": 4,
    "Myotis emarginatus": 4,
    "Vespertilio murinus": 4,
    "Pipistrellus kuhlii": 4,           # Steeds vaker
    "Myotis myotis": 5,                 # Extreem zeldzaam
    "Myotis alcathoe": 5,
    "Rhinolophus ferrumequinum": 5,      # Uitgestorven in NL
    "Rhinolophus hipposideros": 5,       # Uitgestorven in NL
}


def get_dutch_name(scientific: str) -> str:
    """Haal Nederlandse naam op voor wetenschappelijke naam."""
    return SPECIES_DUTCH.get(scientific, scientific)


def get_rarity(scientific: str) -> int:
    """Haal zeldzaamheid op (1-5). Default 3."""
    return SPECIES_RARITY_NL.get(scientific, 3)


def is_rare(scientific: str, threshold: int = 4) -> bool:
    """Is deze soort zeldzaam?"""
    return get_rarity(scientific) >= threshold
