"""Pythagorean + Vedic numerology — deterministic math. No network, no LLM.

Computes the full number set (not just Life Path) on BOTH the solar birthday and
the Chinese lunar birthday, with each number's Vedic planet ruler — so the LLM
can give a real reading instead of a Life-Path one-liner.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_LETTER_VALUES = {c: (i % 9) + 1 for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
_VOWELS = set("AEIOU")
_MASTER_NUMBERS = {11, 22, 33}

NUMBER_TITLES = {
    1: "The Leader", 2: "The Diplomat", 3: "The Communicator", 4: "The Builder",
    5: "The Free Spirit", 6: "The Nurturer", 7: "The Seeker", 8: "The Powerhouse",
    9: "The Humanitarian", 11: "The Visionary (Master)", 22: "The Master Builder",
    33: "The Master Teacher",
}
NUMBER_PLANET = {
    1: "Sun", 2: "Moon", 3: "Jupiter", 4: "Rahu", 5: "Mercury", 6: "Venus",
    7: "Ketu", 8: "Saturn", 9: "Mars", 11: "Moon/Master", 22: "Rahu/Master",
    33: "Jupiter/Master",
}


@dataclass
class NumerologyReport:
    name: str
    birth: date
    life_path: int      # conductor — the whole journey (full DOB)
    day: int            # driver — core self (day of birth)
    month: int          # karmic backdrop
    year: int           # generational vibration
    expression: int     # destiny — talents (full name)
    soul_urge: int      # inner craving (vowels)
    personality: int    # outward impression (consonants)
    maturity: int       # later-life realization (life_path + expression)


@dataclass
class LunarNumbers:
    lunar_month: int
    lunar_day: int
    driver: int         # lunar day reduced (the "lunar root")
    month_number: int   # lunar month reduced


def _reduce(n: int, keep_master: bool = True) -> int:
    while n > 9:
        if keep_master and n in _MASTER_NUMBERS:
            return n
        n = sum(int(d) for d in str(n))
    return n


def _letters(name: str) -> str:
    return "".join(ch for ch in name.upper() if ch.isalpha())


def life_path_number(birth: date) -> int:
    return _reduce(_reduce(birth.month) + _reduce(birth.day)
                   + _reduce(sum(int(d) for d in str(birth.year))))


def expression_number(name: str) -> int:
    total = sum(_LETTER_VALUES[c] for c in _letters(name))
    return _reduce(total) if total else 0


def soul_urge_number(name: str) -> int:
    total = sum(_LETTER_VALUES[c] for c in _letters(name) if c in _VOWELS)
    return _reduce(total) if total else 0


def personality_number(name: str) -> int:
    total = sum(_LETTER_VALUES[c] for c in _letters(name) if c not in _VOWELS)
    return _reduce(total) if total else 0


def build_report(name: str, birth: date) -> NumerologyReport:
    life_path = life_path_number(birth)
    expression = expression_number(name)
    return NumerologyReport(
        name=name.strip(),
        birth=birth,
        life_path=life_path,
        day=_reduce(birth.day),
        month=_reduce(birth.month),
        year=_reduce(sum(int(d) for d in str(birth.year))),
        expression=expression,
        soul_urge=soul_urge_number(name),
        personality=personality_number(name),
        maturity=_reduce(life_path + expression) if (life_path and expression) else 0,
    )


def lunar_numbers(lunar_month: int, lunar_day: int) -> LunarNumbers:
    return LunarNumbers(
        lunar_month=lunar_month,
        lunar_day=lunar_day,
        driver=_reduce(lunar_day),
        month_number=_reduce(lunar_month),
    )


def title(number: int) -> str:
    return NUMBER_TITLES.get(number, "Unknown")


def planet(number: int) -> str:
    return NUMBER_PLANET.get(number, "—")
