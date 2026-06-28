"""Gematria engine — ported from the AUREON Gematria v2 calculator.

Deterministic: English ordinal / full-reduction / reverse / Chaldean ciphers,
soul (vowels) & personality (consonants) splits, planet + element signature,
trigger-number scan, date synchronicity, and power-word resonance. No network,
no LLM. For entertainment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Planet table: (name, symbol, element, element symbol, description, compat, enemy)
PLANETS = [
    ("Sun", "☉", "Fire", "🔥", "authority, leadership, ego, fame", {1, 2, 3}, {6, 7}),
    ("Moon", "☽", "Water", "💧", "masses, emotion, cycles, public mood", {2, 7}, {8}),
    ("Jupiter", "♃", "Ether", "✨", "expansion, wisdom, abundance, law", {3, 6, 9}, set()),
    ("Rahu/Uranus", "☊", "Air", "💨", "disruption, obsession, technology", {4, 5, 8}, {1, 9}),
    ("Mercury", "☿", "Air", "💨", "communication, trade, speed, media", {5, 1, 6}, set()),
    ("Venus", "♀", "Water", "💧", "beauty, luxury, love, art, brand", {6, 3, 9}, {1}),
    ("Ketu/Neptune", "☋", "Water", "💧", "mysticism, hidden knowledge, dissolution", {7, 2}, {1, 8}),
    ("Saturn", "♄", "Earth", "🌍", "karma, discipline, wealth, time, structure", {8, 4, 1}, {2, 7}),
    ("Mars", "♂", "Fire", "🔥", "action, war, ambition, courage", {9, 3, 6}, {4}),
]

CHALDEAN = {
    "A": 1, "I": 1, "J": 1, "Q": 1, "Y": 1, "B": 2, "K": 2, "R": 2,
    "C": 3, "G": 3, "L": 3, "S": 3, "D": 4, "M": 4, "T": 4,
    "E": 5, "H": 5, "N": 5, "X": 5, "U": 6, "V": 6, "W": 6,
    "O": 7, "Z": 7, "F": 8, "P": 8,
}

TRIGGER_CODES = {
    11: "Gateway / magician portal", 13: "Transformation / death & rebirth",
    22: "Master builder / hidden architect", 33: "Master teacher",
    38: "Death coding (ritual events)", 44: "Foundation / underground power",
    47: "Compass / government / authority", 55: "Massive disruption / paradigm shift",
    66: "Double Venus — materialism", 74: "God number of English",
    77: "Double Neptune — occult veil", 88: "Double Saturn — karmic lock",
    93: "Saturn × Jupiter — slow empire rise", 99: "Double Mars — war/destruction",
}

POWER_WORDS = {
    "DEATH": 38, "KILL": 44, "MONEY": 72, "POWER": 77, "BLOOD": 47, "GOD": 26,
    "TRUTH": 87, "LIGHT": 56, "DARK": 35, "FIRE": 38, "WAR": 42, "PEACE": 35,
    "LOVE": 54, "HATE": 35, "LIFE": 32, "TIME": 47, "GOLD": 38, "SILVER": 80,
    "SUN": 54, "MOON": 51, "STAR": 58, "EARTH": 52, "WATER": 67, "SPIRIT": 91,
    "SOUL": 54, "MIND": 40, "BIRTH": 62, "KING": 41, "QUEEN": 62, "EMPIRE": 68,
    "FREE": 29, "FEAR": 30, "HOPE": 42, "CHAOS": 46, "ORDER": 51, "BANK": 27,
    "JESUS": 74, "SATAN": 55, "MASON": 62, "CROSS": 74, "CROWN": 74, "MATRIX": 74,
    "RITUAL": 81, "VIRUS": 89, "VOTE": 67, "LAW": 33, "CODE": 27,
}

_VOWELS = set("AEIOU")
_HIDDEN = ["RA", "EL", "IS", "AL", "AN", "ON", "OR", "RE", "DE", "MA", "EN", "IA", "AH", "IO"]
_TRI = {"GOD", "SUN", "WAR", "LAW", "ARC", "ORB", "EYE", "ALL"}


def _ordinal(c: str) -> int:
    return ord(c) - 64 if "A" <= c <= "Z" else 0


def _reverse(c: str) -> int:
    return 27 - (ord(c) - 64) if "A" <= c <= "Z" else 0


def reduce(n: int) -> int:
    """Digital root, preserving master numbers 11/22/33."""
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(d) for d in str(n))
    return n


def _full(c: str) -> int:
    return reduce(_ordinal(c)) if _ordinal(c) else 0


def planet(n: int) -> tuple:
    return PLANETS[(n - 1) % 9]


def _letters(word: str) -> list[str]:
    return [c for c in word.upper() if "A" <= c <= "Z"]


@dataclass
class Analysis:
    word: str
    ordinal: int
    reverse: int
    full: int
    chaldean: int
    o_root: int
    r_root: int
    f_root: int
    c_root: int
    soul: int          # vowels sum
    soul_root: int
    persona: int       # consonants sum
    persona_root: int
    dominant_root: int
    confidence: int
    elements: dict
    dom_element: str
    triggers: list[tuple[int, str]]
    masters: list[int]
    hidden: list[str]


def analyze(word: str) -> Analysis | None:
    letters = _letters(word)
    if not letters:
        return None
    o = sum(_ordinal(c) for c in letters)
    r = sum(_reverse(c) for c in letters)
    f = sum(_full(c) for c in letters)
    c = sum(CHALDEAN.get(ch, 0) for ch in letters)
    o_root, r_root, f_root, c_root = reduce(o), reduce(r), reduce(f), reduce(c)

    soul = sum(_ordinal(ch) for ch in letters if ch in _VOWELS)
    persona = sum(_ordinal(ch) for ch in letters if ch not in _VOWELS)
    soul_root = reduce(soul) if soul else 0
    persona_root = reduce(persona) if persona else 0

    counts: dict[int, int] = {}
    for root in (o_root, f_root, c_root):
        counts[root] = counts.get(root, 0) + 1
    dominant_root, top = max(counts.items(), key=lambda kv: kv[1])
    confidence = round(top / 3 * 100)

    elements = {"Fire": 0, "Water": 0, "Air": 0, "Earth": 0, "Ether": 0}
    for root in (o_root, r_root, f_root, c_root):
        elements[planet(root)[2]] += 1
    dom_element = max(elements.items(), key=lambda kv: kv[1])[0]

    scanned, seen = [], set()
    masters: list[int] = []
    for n in (o, f, r, c, o_root, r_root, f_root, c_root):
        if n in seen:
            continue
        seen.add(n)
        if n in TRIGGER_CODES:
            scanned.append((n, TRIGGER_CODES[n]))
        if n in (11, 22, 33):
            masters.append(n)

    upper = "".join(letters)
    hidden = [hw for hw in _HIDDEN if hw in upper]
    for i in range(len(upper) - 2):
        if upper[i:i + 3] in _TRI:
            hidden.append(upper[i:i + 3])

    return Analysis(
        word=word.strip(), ordinal=o, reverse=r, full=f, chaldean=c,
        o_root=o_root, r_root=r_root, f_root=f_root, c_root=c_root,
        soul=soul, soul_root=soul_root, persona=persona, persona_root=persona_root,
        dominant_root=dominant_root, confidence=confidence,
        elements=elements, dom_element=dom_element,
        triggers=scanned, masters=masters, hidden=sorted(set(hidden)),
    )


@dataclass
class DateSync:
    word_root: int
    date_sum: int
    date_root: int
    verdict: str  # "bind" | "harmonic" | "misaligned"


def date_sync(word: str, d: date) -> DateSync | None:
    a = analyze(word)
    if not a:
        return None
    date_sum = d.year + d.month + d.day
    date_root = reduce(date_sum)
    wr = a.o_root
    if wr == date_root:
        verdict = "bind"
    elif date_root in planet(wr)[5] or wr in planet(date_root)[5]:
        verdict = "harmonic"
    else:
        verdict = "misaligned"
    return DateSync(word_root=wr, date_sum=date_sum, date_root=date_root, verdict=verdict)


@dataclass
class Resonance:
    root: int
    exact: list[tuple[str, int]]
    root_matches: list[tuple[str, int]]


def resonance(word: str) -> Resonance | None:
    letters = _letters(word)
    if not letters:
        return None
    total = sum(_ordinal(c) for c in letters)
    root = reduce(total)
    upper = "".join(letters)
    exact = [(w, v) for w, v in POWER_WORDS.items() if v == total and w != upper]
    root_matches = [(w, v) for w, v in POWER_WORDS.items() if reduce(v) == root and w != upper]
    return Resonance(root=root, exact=exact, root_matches=root_matches)
