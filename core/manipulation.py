"""Detect manipulation / social-engineering *tactics* in a message.

This flags scam/manipulation BEHAVIOUR (phishing, impersonation, money-doubler,
fake account-verification, giveaway bait) — not a person's character. High
precision is the goal: it should warn about real scam patterns, not accuse people
for ordinary talk. Returns a tactic label, or None.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("credential phishing", re.compile(
        r"\b(?:send|give|tell|dm|hand\s+over)\s+(?:me|us)\b[\s\S]{0,20}?\b"
        r"(password|2fa|seed\s*phrase|recovery\s*phrase|login|verification\s+code|"
        r"backup\s+code|otp|private\s+key|credentials?)\b"
        r"|\bwhat(?:'?s| is)\s+your\s+(?:password|login|2fa|otp|seed\s*phrase)\b",
        re.IGNORECASE)),
    ("fake account-verification", re.compile(
        r"\b(?:your\s+)?account\b[\s\S]{0,30}?\b(?:suspend\w*|disabl\w*|lock\w*|terminat\w*|ban\w*)\b"
        r"[\s\S]{0,30}?\b(?:click|verify|confirm|log\s*in|link|here)\b"
        r"|\b(?:verify|confirm)\s+your\s+account\b[\s\S]{0,20}?\b(?:click|link|here|now)\b",
        re.IGNORECASE)),
    ("giveaway / free-gift bait", re.compile(
        r"\b(?:free\s+(?:nitro|gift\s*cards?|robux|v-?bucks|crypto|bitcoins?)|"
        r"claim\s+your\s+(?:free|prize|reward|gift)|you(?:'ve)?\s+(?:have\s+)?won\b)",
        re.IGNORECASE)),
    ("money-doubler scam", re.compile(
        r"\b(?:send|deposit|invest)\b[\s\S]{0,20}?[\$\d][\s\S]{0,25}?"
        r"\b(?:double|triple|x2|guaranteed\s+(?:return|profit)|get\s+back\s+(?:double|more))\b",
        re.IGNORECASE)),
    ("staff impersonation", re.compile(
        r"\bi\s*(?:'?m|\s+am)\b[\s\S]{0,20}?\b(?:discord\s+)?"
        r"(?:staff|admin(?:istrator)?|moderator|support|official\s+team)\b"
        r"[\s\S]{0,40}?\b(?:dm|message|contact|reach\s+out)\b",
        re.IGNORECASE)),
]


def detect(text: str) -> str | None:
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            return label
    return None
