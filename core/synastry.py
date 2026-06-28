"""Deterministic compatibility scoring for /synastry.

Blends numerology (Life Path harmony) and Chinese zodiac (animal trine/clash)
into a 0-100 score. The LLM narrates it. Both people's data is supplied by the
person running the command — no third-party data is harvested.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core import numerology, lunar

# Chinese zodiac trines (best matches) and direct clashes (opposite on the wheel).
_ANIMALS = ["Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
            "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig"]
_TRINES = [{"Rat", "Dragon", "Monkey"}, {"Ox", "Snake", "Rooster"},
           {"Tiger", "Horse", "Dog"}, {"Rabbit", "Goat", "Pig"}]

# Numerology life-path harmony (1-9): simple resonance groups.
_NUM_HARMONY = {
    frozenset({1, 5, 7}): 18, frozenset({2, 4, 8}): 18, frozenset({3, 6, 9}): 18,
}


@dataclass
class Match:
    name_a: str
    name_b: str
    life_path_a: int
    life_path_b: int
    animal_a: str
    animal_b: str
    score: int
    headline: str


def _animal_points(a: str, b: str) -> int:
    if a == b:
        return 24
    for trine in _TRINES:
        if a in trine and b in trine:
            return 30
    # clash = 6 signs apart
    if abs(_ANIMALS.index(a) - _ANIMALS.index(b)) == 6:
        return 6
    return 16


def _number_points(a: int, b: int) -> int:
    if a == b:
        return 16
    for group, pts in _NUM_HARMONY.items():
        if a in group and b in group:
            return pts
    return 10


def compute(name_a: str, date_a: date, name_b: str, date_b: date) -> Match:
    lp_a = numerology.life_path_number(date_a)
    lp_b = numerology.life_path_number(date_b)
    an_a = lunar.to_lunar(date_a).year_animal
    an_b = lunar.to_lunar(date_b).year_animal

    score = _animal_points(an_a, an_b) + _number_points(lp_a, lp_b)
    score = max(5, min(score + 40, 100))  # baseline + cap

    if score >= 80:
        headline = "Strong resonance"
    elif score >= 60:
        headline = "Warm, workable harmony"
    elif score >= 40:
        headline = "Growth through contrast"
    else:
        headline = "Friction — needs conscious effort"

    return Match(name_a=name_a, name_b=name_b, life_path_a=lp_a, life_path_b=lp_b,
                 animal_a=an_a, animal_b=an_b, score=score, headline=headline)
