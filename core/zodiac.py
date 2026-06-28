"""Chinese zodiac — deterministic animal + element from birth year.

Uses Feb 4 as a simple solar-year boundary approximation (the true boundary is
Li Chun / Chinese New Year, which varies; readings note this).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ANIMALS = [
    ("Rat", "the Quick — clever, resourceful, alert"),
    ("Ox", "the Foundation — steady, patient, dependable"),
    ("Tiger", "the Predator — brave, magnetic, competitive"),
    ("Rabbit", "the Elegant — gentle, refined, diplomatic"),
    ("Dragon", "the Celestial — charismatic, ambitious, proud"),
    ("Snake", "the Enigmatic — intuitive, private, hypnotic"),
    ("Horse", "the Athlete — free, energetic, restless"),
    ("Goat", "the Contemplative — artistic, kind, dreamy"),
    ("Monkey", "the Trickster — witty, inventive, playful"),
    ("Rooster", "the Sentinel — observant, confident, stylish"),
    ("Dog", "the Guardian — loyal, sincere, just"),
    ("Pig", "the Epicurean — generous, sincere, comfort-loving"),
]

ELEMENTS = ["Wood", "Fire", "Earth", "Metal", "Water"]


@dataclass
class ZodiacSign:
    animal: str
    animal_traits: str
    element: str
    year: int


def _effective_year(birth: date) -> int:
    # Years before ~Feb 4 belong to the previous Chinese year (approximation).
    return birth.year - 1 if (birth.month, birth.day) < (2, 4) else birth.year


def compute_sign(birth: date) -> ZodiacSign:
    y = _effective_year(birth)
    animal, traits = ANIMALS[(y - 4) % 12]
    element = ELEMENTS[((y - 4) % 10) // 2]
    return ZodiacSign(animal=animal, animal_traits=traits, element=element, year=y)
