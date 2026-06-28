"""Deterministic-random draws for /tarot and /iching. The LLM narrates the result."""
from __future__ import annotations

import random
from dataclasses import dataclass

MAJOR_ARCANA = [
    ("The Fool", "beginnings, leap of faith, innocence"),
    ("The Magician", "will, manifestation, resourcefulness"),
    ("The High Priestess", "intuition, mystery, the unseen"),
    ("The Empress", "abundance, nurture, creation"),
    ("The Emperor", "structure, authority, control"),
    ("The Hierophant", "tradition, teaching, belief"),
    ("The Lovers", "union, choice, alignment"),
    ("The Chariot", "drive, willpower, victory"),
    ("Strength", "courage, patience, inner power"),
    ("The Hermit", "solitude, search, inner light"),
    ("Wheel of Fortune", "cycles, fate, turning points"),
    ("Justice", "truth, cause and effect, balance"),
    ("The Hanged Man", "surrender, new perspective, pause"),
    ("Death", "endings, transformation, release"),
    ("Temperance", "balance, blending, patience"),
    ("The Devil", "attachment, shadow, bondage"),
    ("The Tower", "sudden change, upheaval, revelation"),
    ("The Star", "hope, renewal, guidance"),
    ("The Moon", "illusion, dreams, the subconscious"),
    ("The Sun", "joy, clarity, vitality"),
    ("Judgement", "awakening, reckoning, rebirth"),
    ("The World", "completion, wholeness, arrival"),
]

HEXAGRAMS = [
    "The Creative", "The Receptive", "Difficulty at the Beginning", "Youthful Folly",
    "Waiting", "Conflict", "The Army", "Holding Together", "Small Taming", "Treading",
    "Peace", "Standstill", "Fellowship", "Great Possession", "Modesty", "Enthusiasm",
    "Following", "Work on the Decayed", "Approach", "Contemplation", "Biting Through",
    "Grace", "Splitting Apart", "Return", "Innocence", "Great Taming", "Nourishment",
    "Great Excess", "The Abysmal", "The Clinging", "Influence", "Duration", "Retreat",
    "Great Power", "Progress", "Darkening of the Light", "The Family", "Opposition",
    "Obstruction", "Deliverance", "Decrease", "Increase", "Breakthrough", "Coming to Meet",
    "Gathering Together", "Pushing Upward", "Oppression", "The Well", "Revolution",
    "The Cauldron", "The Arousing", "Keeping Still", "Development", "The Marrying Maiden",
    "Abundance", "The Wanderer", "The Gentle", "The Joyous", "Dispersion", "Limitation",
    "Inner Truth", "Small Exceeding", "After Completion", "Before Completion",
]


@dataclass
class TarotDraw:
    cards: list[tuple[str, str, bool]]  # (name, meaning, reversed)


@dataclass
class IChingCast:
    number: int
    name: str
    changing_lines: list[int]


def draw_tarot(count: int = 3, seed: int | None = None) -> TarotDraw:
    rng = random.Random(seed)
    picked = rng.sample(MAJOR_ARCANA, k=min(count, len(MAJOR_ARCANA)))
    return TarotDraw(cards=[(n, m, rng.random() < 0.5) for n, m in picked])


def cast_iching(seed: int | None = None) -> IChingCast:
    rng = random.Random(seed)
    lines = [rng.choice((6, 7, 8, 9)) for _ in range(6)]  # 6/9 are changing
    # Map the six lines (bottom-up) to a King Wen number via binary yin/yang.
    bits = "".join("1" if v in (7, 9) else "0" for v in lines)
    number = (int(bits, 2) % 64) + 1
    changing = [i + 1 for i, v in enumerate(lines) if v in (6, 9)]
    return IChingCast(number=number, name=HEXAGRAMS[number - 1], changing_lines=changing)
