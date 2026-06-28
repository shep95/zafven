"""For-fun 'communication vibe' stats from a member's own recent messages.

Surface features only — opt-in, self-only. Not psychology, not profiling.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
URL_RE = re.compile(r"https?://\S+")
WORD_RE = re.compile(r"[a-zA-Z']+")

SLANG = {
    "lol", "lmao", "lmfao", "bruh", "fr", "ngl", "tbh", "imo", "rip", "gg",
    "based", "cope", "ez", "yeet", "sus", "vibe", "vibes", "lowkey", "highkey",
    "deadass", "bet", "smh", "idk", "omg", "wtf", "fyi", "btw",
}

_STOPWORDS = {
    "this", "that", "with", "have", "from", "they", "them", "what", "when",
    "your", "youre", "just", "like", "dont", "cant", "wont", "yeah", "really",
    "going", "gonna", "wanna", "about", "would", "could", "should", "there",
    "their", "then", "than", "been", "were", "will", "didnt", "doesnt", "thing",
    "things", "people", "because", "every", "some", "much", "very",
}


@dataclass
class VibeStats:
    messages: int = 0
    words: int = 0
    emoji: int = 0
    caps_words: int = 0
    questions: int = 0
    exclamations: int = 0
    links: int = 0
    slang_hits: int = 0
    top_emoji: list[tuple[str, int]] = field(default_factory=list)
    top_words: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class VibeResult:
    archetype: str
    stats: VibeStats


def analyze(messages: list[str]) -> VibeResult:
    s = VibeStats(messages=len(messages))
    emoji_counter: Counter[str] = Counter()
    word_counter: Counter[str] = Counter()

    for content in messages:
        s.links += len(URL_RE.findall(content))
        text = URL_RE.sub("", content)
        unicode_emoji = EMOJI_RE.findall(text)
        custom_emoji = CUSTOM_EMOJI_RE.findall(text)
        s.emoji += len(unicode_emoji) + len(custom_emoji)
        emoji_counter.update(unicode_emoji)
        emoji_counter.update(re.findall(r":(\w+):", " ".join(custom_emoji)))
        s.questions += text.count("?")
        s.exclamations += text.count("!")
        for w in WORD_RE.findall(text):
            lw = w.lower()
            s.words += 1
            if len(w) >= 3 and w.isupper():
                s.caps_words += 1
            if lw in SLANG:
                s.slang_hits += 1
            if len(lw) >= 4 and lw not in _STOPWORDS:
                word_counter[lw] += 1

    s.top_emoji = emoji_counter.most_common(5)
    s.top_words = word_counter.most_common(5)
    return VibeResult(archetype=_pick_archetype(s), stats=s)


def _ratio(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _pick_archetype(s: VibeStats) -> str:
    emoji_per_msg = _ratio(s.emoji, s.messages)
    avg_words = _ratio(s.words, s.messages)
    caps_ratio = _ratio(s.caps_words, s.words)
    question_per_msg = _ratio(s.questions, s.messages)
    slang_ratio = _ratio(s.slang_hits, s.words)

    if emoji_per_msg >= 1.5:
        return "The Emoji Bard 🎭"
    if caps_ratio >= 0.08:
        return "The Town Crier 📣"
    if question_per_msg >= 0.6:
        return "The Curious Cat 🐈"
    if slang_ratio >= 0.12:
        return "The Meme Fluent 🗿"
    if avg_words >= 25:
        return "The Essayist 📜"
    if avg_words <= 4 and s.messages >= 10:
        return "The Minimalist 🥷"
    if _ratio(s.links, s.messages) >= 0.4:
        return "The Curator 🔗"
    if s.exclamations >= s.messages:
        return "The Hype Engine ⚡"
    return "The Steady Voice 🌿"
