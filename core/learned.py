"""Community-taught knowledge base — the corrections users teach Zafven.

When she gets something wrong and a user corrects her (a reply to her answer, or
the /teach command), the corrected fact is filed here per guild. On future
questions the relevant facts are retrieved (keyword overlap) and injected so she
prefers the community's correction over her own earlier guess.

Additive knowledge only: it never overrides her safety lines, and clearly false
or harmful "lessons" can be pruned by mods via /unlearn.
"""
from __future__ import annotations

import re
import time

import discord

from core import store

NS = "learned"
MAX_ENTRIES = 400
MAX_TOPIC = 120
MAX_FACT = 600
RETRIEVE = 4  # how many facts to pull into a given answer

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "are", "was", "you", "your", "that", "this", "with", "from",
    "what", "when", "where", "which", "who", "why", "how", "does", "did", "can", "could",
    "would", "should", "about", "into", "than", "then", "they", "them", "its", "his", "her",
    "have", "has", "had", "but", "not", "all", "any", "out", "get", "got", "one", "two",
    "actually", "really", "just", "like", "yeah", "okay",
}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


async def _load(guild: discord.Guild) -> tuple[object, list[dict]]:
    s = await store.get_store(guild)
    return s, list(s.get(NS, []) or [])


async def add(guild: discord.Guild, topic: str, fact: str, taught_by: int = 0) -> bool:
    topic = (topic or "").strip()[:MAX_TOPIC]
    fact = (fact or "").strip()[:MAX_FACT]
    if not fact:
        return False
    s, entries = await _load(guild)
    key = (topic.lower(), fact.lower())
    entries = [e for e in entries
               if (e.get("topic", "").lower(), e.get("fact", "").lower()) != key]
    entries.append({"topic": topic, "fact": fact, "by": taught_by, "ts": int(time.time())})
    await s.set(NS, entries[-MAX_ENTRIES:])
    return True


async def all_entries(guild: discord.Guild) -> list[dict]:
    _s, e = await _load(guild)
    return e


async def relevant(guild: discord.Guild, query: str, limit: int = RETRIEVE) -> list[dict]:
    _s, entries = await _load(guild)
    if not entries:
        return []
    q = set(_tokens(query))
    if not q:
        return []
    scored: list[tuple[int, dict]] = []
    for e in entries:
        toks = set(_tokens(f"{e.get('topic', '')} {e.get('fact', '')}"))
        overlap = len(q & toks)
        if overlap:
            scored.append((overlap, e))
    scored.sort(key=lambda x: (-x[0], -x[1].get("ts", 0)))
    return [e for _score, e in scored[:limit]]


async def remove(guild: discord.Guild, index: int) -> dict | None:
    s, entries = await _load(guild)
    if 0 <= index < len(entries):
        gone = entries.pop(index)
        await s.set(NS, entries)
        return gone
    return None


async def clear(guild: discord.Guild) -> None:
    s, _e = await _load(guild)
    await s.set(NS, [])


def format_for_prompt(entries: list[dict]) -> str:
    out = []
    for e in entries:
        topic = e.get("topic", "")
        out.append(f"- {topic}: {e['fact']}" if topic else f"- {e['fact']}")
    return "\n".join(out)
