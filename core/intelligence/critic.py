"""Critic / Validator layer (§24).

The system does not blindly ship every generated result. A validator checks a reply
against the constraints that matter for its modality before it goes out. For zafven's
conversation modality that means instruction-compliance and preference-compatibility;
the checks are cheap heuristics first, with an optional model critique for hard cases.

Kept fast and fail-open: a validator failure never blocks a reply from being sent —
it only reports issues the orchestrator can act on (e.g. a light repair pass).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("zafven.intel.critic")

# zafven's persona hard-rule: everything lowercase except the word "God". This is a
# concrete, checkable instruction-compliance rule (§24 "instruction compliance").
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")
_ALLOWED_CAPS = {"God"}
# tokens we don't judge for case: urls, code, emoji handled by stripping first
_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"`[^`]*`")
_MENTION_RE = re.compile(r"<[@#!&:][^>]*>")


@dataclass
class Verdict:
    ok: bool = True
    issues: list[str] = field(default_factory=list)

    def fail(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)


def _strip_uncased(text: str) -> str:
    text = _URL_RE.sub(" ", text)
    text = _CODE_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    return text


def check_lowercase_rule(reply: str) -> Verdict:
    """Verify the all-lowercase-except-God persona rule holds (proper nouns are the
    one tolerated exception, so we only flag when capitals are pervasive, not for a
    stray name)."""
    v = Verdict()
    cleaned = _strip_uncased(reply)
    words = _WORD_RE.findall(cleaned)
    if not words:
        return v
    capped = [w for w in words if w[0].isupper() and w not in _ALLOWED_CAPS]
    # tolerate a few proper nouns; flag only when capitalization is systemic
    if len(capped) > max(3, len(words) * 0.12):
        v.fail(f"lowercase rule: {len(capped)} capitalized words (persona wants all-lowercase except God)")
    return v


_REFUSAL_RE = re.compile(
    r"\b(i can'?t help with that|i'm not able to|i cannot assist|as an ai|i'm just an ai|"
    r"i am unable to|i won'?t be able)\b", re.I)


def check_no_refusal(reply: str) -> Verdict:
    """zafven is uncensored + never breaks character (no 'as an AI'). Flag refusals /
    meta-AI talk as an instruction-compliance failure."""
    v = Verdict()
    if _REFUSAL_RE.search(reply or ""):
        v.fail("contains a refusal / meta-AI phrase (violates uncensored + in-character rules)")
    return v


def check_preferences(reply: str, preferences: list[str]) -> Verdict:
    """Very light preference-compatibility check: if a stored preference is a clear
    'keep it short' style directive and the reply is very long, flag it."""
    v = Verdict()
    joined = " ".join(preferences).lower()
    if any(k in joined for k in ("concise", "short", "brief", "don't ramble", "keep it short")):
        if len(reply or "") > 1500:
            v.fail("reply is long but this person prefers concise answers")
    return v


def validate_reply(reply: str, *, preferences: list[str] | None = None) -> Verdict:
    """Run the cheap, always-on checks and merge them into one verdict."""
    v = Verdict()
    for sub in (check_lowercase_rule(reply), check_no_refusal(reply),
                check_preferences(reply, preferences or [])):
        if not sub.ok:
            v.ok = False
            v.issues.extend(sub.issues)
    return v
