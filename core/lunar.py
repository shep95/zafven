"""Chinese lunisolar calendar + zodiac pillars (year / month / day).

Converts a Gregorian birth date to its Chinese lunar date and derives the three
animal "pillars" the user asked for:
  * Year animal + element — uses the true lunar-new-year boundary (via lunardate),
    not a fixed Feb-4 guess.
  * Month animal (the "inner self") — from the lunar month.
  * Day animal (the "secret self") — from the 60-day sexagenary cycle.

Verified: Gregorian 2005-09-26 -> lunar month 8, day 23 (Wood Rooster year).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lunardate import LunarDate

# index by (lunar_year - 4) % 12; 0 = Rat
YEAR_ANIMALS = [
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

# Month animal: lunar month 1 = Tiger, 2 = Rabbit, ...
_MONTH_ORDER = ["Tiger", "Rabbit", "Dragon", "Snake", "Horse", "Goat",
                "Monkey", "Rooster", "Dog", "Pig", "Rat", "Ox"]

# Day animal: 60-day sexagenary cycle. 2000-01-07 was a Jia-Zi (Rat) day.
_DAY_ANCHOR = date(2000, 1, 7)
_BRANCH_ANIMALS = ["Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
                   "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig"]


@dataclass
class LunarInfo:
    greg: date
    lunar_year: int
    lunar_month: int
    lunar_day: int
    leap_month: bool
    year_animal: str
    year_animal_traits: str
    element: str
    month_animal: str   # inner self
    day_animal: str     # secret self


def to_lunar(greg: date) -> LunarInfo:
    ld = LunarDate.fromSolarDate(greg.year, greg.month, greg.day)
    animal, traits = YEAR_ANIMALS[(ld.year - 4) % 12]
    element = ELEMENTS[((ld.year - 4) % 10) // 2]
    month_animal = _MONTH_ORDER[(ld.month - 1) % 12]
    day_animal = _BRANCH_ANIMALS[(greg.toordinal() - _DAY_ANCHOR.toordinal()) % 12]
    return LunarInfo(
        greg=greg,
        lunar_year=ld.year,
        lunar_month=ld.month,
        lunar_day=ld.day,
        leap_month=bool(ld.isLeapMonth),
        year_animal=animal,
        year_animal_traits=traits,
        element=element,
        month_animal=month_animal,
        day_animal=day_animal,
    )
