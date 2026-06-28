"""Heuristic cyberbullying / harassment detection.

Conservative by design: self-harm encouragement always flags; demeaning insults
only flag when they're clearly aimed at a person ("you're worthless", "kys").
Returns a short category string, or None.
"""
from __future__ import annotations

import re

# Always-flag: encouraging self-harm / death.
_SELF_HARM = re.compile(
    r"\b(k+\s*y+\s*s+|kill\s*(your\s*self|urself|yourself)|go\s+(and\s+)?die|"
    r"you\s+should\s+(?:\w+\s+){0,2}(die|kill)|neck\s+(your\s*self|yourself)|end\s+(your\s*self|yourself|your\s+life)|"
    r"hang\s+(your\s*self|yourself)|drink\s+bleach|slit\s+your|nobody\s+(would|will)\s+miss\s+you|"
    r"(world|everyone)\s+(would\s+be\s+)?better\s+(off\s+)?without\s+you)\b",
    re.IGNORECASE,
)

# Demeaning terms that count as bullying when aimed at a person.
_INSULTS = (r"worthless|pathetic|stupid|idiot|moron|dumb|ugly|fat|loser|freak|"
            r"retard(?:ed)?|waste\s+of\s+(?:space|air|oxygen|skin)|"
            r"(?:a\s+)?(?:joke|mistake|failure|disgrace)")

# "you('re) ... <insult>"  or  "<insult> ... you"
_DIRECTED = re.compile(rf"\byou(?:'?re| are)?\b[\w\s,']{{0,24}}\b(?:{_INSULTS})\b", re.IGNORECASE)
_DIRECTED2 = re.compile(rf"\b(?:{_INSULTS})\b[\w\s,']{{0,12}}\byou\b", re.IGNORECASE)

# Group-pile-on phrases.
_GROUP = re.compile(r"\b(nobody|no\s*one|everyone)\s+(likes|loves|wants|hates)\s+you\b", re.IGNORECASE)


def detect(text: str) -> str | None:
    if _SELF_HARM.search(text):
        return "encouraging self-harm"
    if _GROUP.search(text):
        return "targeted harassment"
    if _DIRECTED.search(text) or _DIRECTED2.search(text):
        return "a targeted insult"
    return None
