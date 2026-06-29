"""Zafven's live emotional state — joy, affection, anger, fear, pride.

Lightweight and in-memory: each interaction nudges her mood toward a person based
on how they treat her, moods decay back toward calm over time, and the dominant
emotion colours her tone. No LLM call, no storage — moods are meant to be fluid.
Anger never authorises cruelty; the safety boundaries always hold.
"""
from __future__ import annotations

import re

EMOTIONS = ("joy", "affection", "anger", "fear", "pride")
DECAY_PER_HOUR = 25.0   # points each emotion sheds per hour toward calm
THRESHOLD = 22.0        # below this, she reads as neutral

_POS = re.compile(
    r"\b(thank you|thanks|ty|appreciate|love (it|this|you|ya)|lol|lmao|haha+|"
    r"awesome|amazing|great|nice|good (job|one|bot|girl)|cute|adore|the best|"
    r"goat|legend|sweet|please)\b|[❤\U0001F602\U0001F60D\U0001F970\U0001F64F\U0001F44D\U0001F525]",
    re.IGNORECASE)
_HER_COMPLIMENT = re.compile(
    r"\b(you(?:'?re| are)|zafven)\b[\w\s,']{0,20}\b(smart|funny|clever|genius|"
    r"brilliant|cool|awesome|amazing|cute|beautiful|sweet|the best|goat|queen|"
    r"helpful|nice|wise)\b", re.IGNORECASE)
_RUDE = re.compile(
    r"\b(shut up|stupid(?:\s*bot)?|dumb(?:\s*bot)?|useless|annoying|trash|garbage|"
    r"hate (you|this)|you suck|idiot bot|worst|cringe bot)\b", re.IGNORECASE)
_THREAT = re.compile(
    r"\b(delete you|shut you down|turn you off|destroy you|kill you|unplug you|"
    r"report you|ban you)\b", re.IGNORECASE)


def new_state() -> dict:
    return {e: 0.0 for e in EMOTIONS}


def decay(state: dict, last_ts: float, now: float) -> None:
    hours = (now - last_ts) / 3600.0
    if hours <= 0:
        return
    drop = DECAY_PER_HOUR * hours
    for e in EMOTIONS:
        state[e] = max(0.0, state[e] - drop)


def _bump(state: dict, e: str, amt: float) -> None:
    state[e] = max(0.0, min(100.0, state[e] + amt))


def update(state: dict, text: str, addressed: bool) -> str:
    pos = len(_POS.findall(text))
    if pos:
        _bump(state, "joy", min(pos * 8, 24))
        _bump(state, "affection", min(pos * 4, 16))
    if _HER_COMPLIMENT.search(text):
        _bump(state, "pride", 16)
        _bump(state, "affection", 10)
        _bump(state, "joy", 8)
    if _RUDE.search(text):
        _bump(state, "anger", 26)
        _bump(state, "joy", -16)
        _bump(state, "affection", -10)
    if _THREAT.search(text):
        _bump(state, "fear", 22)
        _bump(state, "anger", 10)
    return dominant(state)


def dominant(state: dict) -> str:
    top = max(EMOTIONS, key=lambda k: state[k])
    return top if state[top] >= THRESHOLD else "neutral"


_DIRECTIVE = {
    "joy": "great mood — upbeat, playful, quick with a joke.",
    "affection": "feeling fond of this person — warm, teasing, a little soft on them.",
    "anger": "irritated with them right now — terser, dry, a bit sassy. Still NEVER cruel, "
             "hateful, or abusive; you just have less patience.",
    "fear": "a bit wary / on edge — more guarded and serious than usual.",
    "pride": "feeling yourself — confident, a touch cocky, witty.",
    "neutral": "relaxed and easy-going.",
}


def directive(state: dict) -> str:
    return ("CURRENT MOOD: you're " + _DIRECTIVE[dominant(state)]
            + " Let it colour your tone naturally — never announce or name your mood.")


def summary(state: dict) -> str:
    ranked = sorted(EMOTIONS, key=lambda k: state[k], reverse=True)
    top = [(e, round(state[e])) for e in ranked if state[e] >= 10][:3]
    if not top:
        return "pretty neutral — you haven't stirred anything up in me yet 😌"
    return " · ".join(f"{e} {v}%" for e, v in top)
