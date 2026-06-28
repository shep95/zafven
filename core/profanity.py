"""Profanity detection + censoring.

Word-boundary, case-insensitive matching against a built-in list (+ any extras
from config), with light leetspeak normalisation so common evasions still match.
Censoring keeps the first letter and stars the rest: "shit" -> "s***".
"""
from __future__ import annotations

import re

import config

# Curated base list of common strong profanity. Extend via PROFANITY_EXTRA_WORDS.
_BASE_WORDS = {
    "fuck", "fucker", "fucking", "motherfucker", "shit", "bullshit", "bitch",
    "bastard", "asshole", "dickhead", "cunt", "slut", "whore", "prick",
    "wanker", "twat", "faggot", "nigger", "nigga", "retard", "cum",
    "cock", "pussy", "dick", "douche", "jackass",
}

# Leetspeak / symbol substitutions applied before detection (not to the output).
_LEET = str.maketrans({"@": "a", "0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "$": "s", "5": "s", "7": "t"})


def _all_words() -> set[str]:
    extra = {w.lower() for w in config.PROFANITY_EXTRA_WORDS}
    return _BASE_WORDS | extra


def _pattern() -> re.Pattern[str]:
    words = sorted(_all_words(), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


_PATTERN = _pattern()


def refresh() -> None:
    """Rebuild the pattern after config changes (e.g. extra words)."""
    global _PATTERN
    _PATTERN = _pattern()


def _normalize(text: str) -> str:
    return text.translate(_LEET)


def count(text: str) -> int:
    """How many profane words appear (counts evasions via normalisation too)."""
    return len(_PATTERN.findall(_normalize(text)))


def _star(word: str) -> str:
    return word[0] + "*" * (len(word) - 1) if len(word) > 1 else "*"


def censor(text: str) -> str:
    """Return the text with profane words starred out.

    Detection runs on a normalised copy; replacement maps back to the original
    spans so the visible message keeps its original (now-starred) characters.
    """
    normalized = _normalize(text)
    result: list[str] = []
    last = 0
    for m in _PATTERN.finditer(normalized):
        start, end = m.span()
        result.append(text[last:start])
        result.append(_star(text[start:end]))
        last = end
    result.append(text[last:])
    return "".join(result)
