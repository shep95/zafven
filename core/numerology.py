"""Pythagorean numerology — deterministic math. No network, no LLM."""
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


@dataclass
class NumerologyReport:
    name: str
    birth: date
    life_path: int
    expression: int
    soul_urge: int
    personality: int
    birthday: int


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


def birthday_number(birth: date) -> int:
    return _reduce(birth.day)


def build_report(name: str, birth: date) -> NumerologyReport:
    return NumerologyReport(
        name=name.strip(),
        birth=birth,
        life_path=life_path_number(birth),
        expression=expression_number(name),
        soul_urge=soul_urge_number(name),
        personality=personality_number(name),
        birthday=birthday_number(birth),
    )


def title(number: int) -> str:
    return NUMBER_TITLES.get(number, "Unknown")
