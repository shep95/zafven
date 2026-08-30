"""Profanity / slur / sexual-language detection + censoring.

Three curated word sets are matched case-insensitively on word boundaries, with
light leetspeak normalisation so common evasions ("n1gga", "f4g", "b!tch") still
match:
  * PROFANITY — strong curse words
  * SLUR      — racist / homophobic / ableist hate slurs
  * SEXUAL    — explicit sexual slang / slurs

`categories(text)` reports which of those a message tripped (so the mod notice can
name it); `count()` and `censor()` operate on the union of all three.
Word-boundary matching keeps the Scunthorpe problem in check ("class", "cockpit",
"pass" don't match). This moderates what *users* post — it's independent of the
bot's own uncensored replies.
"""
from __future__ import annotations

import re

import config

# ── Strong curse words ────────────────────────────────────────────────────
_PROFANITY = {
    "fuck", "fuk", "fuckin", "fucking", "fucked", "fucker", "fuckers", "fuckhead",
    "fuckface", "fuckwit", "motherfucker", "motherfuckers", "motherfucking",
    "shit", "shite", "shitty", "shithead", "bullshit", "dogshit", "batshit",
    "bitch", "bitches", "bitching", "bastard", "bastards",
    "asshole", "assholes", "arsehole", "arseholes", "ass", "arse", "jackass",
    "dumbass", "smartass", "dumbfuck", "dickhead", "dickheads", "prick", "pricks",
    "cock", "cocks", "wanker", "wankers", "twat", "twats", "bollocks",
    "douchebag", "douche", "cunt", "cunts", "piss",
}

# ── Racist / homophobic / ableist hate slurs ──────────────────────────────
_SLUR = {
    "nigger", "niggers", "nigga", "niggas", "niggaz", "niggah", "nigguh",
    "faggot", "faggots", "fag", "fags", "faggy", "dyke", "dykes",
    "tranny", "trannies", "chink", "chinks", "gook", "gooks", "spic", "spics",
    "wetback", "wetbacks", "kike", "kikes", "coon", "coons", "beaner", "beaners",
    "raghead", "ragheads", "towelhead", "towelheads", "sandnigger", "sandniggers",
    "paki", "pakis", "wop", "wops", "dago", "dagos", "gypo", "retard", "retards",
    "retarded", "tard", "tards", "spastic", "mongoloid",
}

# ── Explicit sexual slang / slurs ─────────────────────────────────────────
_SEXUAL = {
    "slut", "sluts", "slutty", "whore", "whores", "cum", "cumming", "cumshot",
    "jizz", "blowjob", "blowjobs", "handjob", "rimjob", "deepthroat", "creampie",
    "gangbang", "bukkake", "dildo", "dildos", "buttplug", "pussy", "pussies",
    "jerkoff", "jackoff", "thot", "thots", "clit", "dickpic", "dickpics",
    "cameltoe", "coochie", "fleshlight", "fleshlight",
}

_CATEGORY_LABEL = {
    "slur": "a hateful slur",
    "sexual": "explicit sexual language",
    "profanity": "strong profanity",
}
# Order the notice lists categories in (worst first).
_CATEGORY_ORDER = ("slur", "sexual", "profanity")

# Leetspeak / symbol substitutions applied before detection (not to the output).
_LEET = str.maketrans({"@": "a", "0": "o", "1": "i", "!": "i", "3": "e",
                       "4": "a", "$": "s", "5": "s", "7": "t"})


def _sets() -> dict[str, set[str]]:
    """The three word sets, with config extras folded into 'profanity'."""
    extra = {w.lower() for w in config.PROFANITY_EXTRA_WORDS if w.strip()}
    return {"profanity": _PROFANITY | extra, "slur": set(_SLUR), "sexual": set(_SEXUAL)}


def _compile(words: set[str]) -> re.Pattern[str]:
    ordered = sorted(words, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in ordered) + r")\b", re.IGNORECASE)


# Per-category patterns (for naming the violation) + one combined pattern.
_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {}
_PATTERN: re.Pattern[str]


def refresh() -> None:
    """Rebuild the patterns after a config change (e.g. extra words)."""
    global _CATEGORY_PATTERNS, _PATTERN
    sets = _sets()
    _CATEGORY_PATTERNS = {cat: _compile(words) for cat, words in sets.items()}
    _PATTERN = _compile(set().union(*sets.values()))


refresh()


def _normalize(text: str) -> str:
    return text.translate(_LEET)


def count(text: str) -> int:
    """How many banned words appear (counts leetspeak evasions too)."""
    return len(_PATTERN.findall(_normalize(text)))


def categories(text: str) -> list[str]:
    """Which categories the text trips, worst-first (['slur', 'sexual', ...])."""
    normalized = _normalize(text)
    return [cat for cat in _CATEGORY_ORDER if _CATEGORY_PATTERNS[cat].search(normalized)]


def describe(text: str) -> str:
    """Human phrase for the tripped categories, e.g. 'a hateful slur and strong profanity'."""
    labels = [_CATEGORY_LABEL[c] for c in categories(text)]
    if not labels:
        return "banned language"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _star(word: str) -> str:
    return word[0] + "*" * (len(word) - 1) if len(word) > 1 else "*"


def censor(text: str) -> str:
    """Return the text with banned words starred out.

    Detection runs on a leetspeak-normalised copy; because normalisation is a
    1:1 character map, spans map straight back onto the original text.
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
