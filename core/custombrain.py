"""Owner-added custom brain content — extra personality, lore, and knowledge.

Layered into Zafven's chat persona as ADDITIVE context. It customizes her flavour
and knowledge; it does not (and structurally cannot) remove her safety lines,
which are reasserted after it. Persisted per guild via the Discord-backed store.
"""
from __future__ import annotations

import discord

from core import store

NS = "custombrain"
MAX_ENTRIES = 25
MAX_LEN = 1500


async def _load(guild: discord.Guild) -> tuple[object, list[str]]:
    s = await store.get_store(guild)
    return s, list((s.get(NS, {}) or {}).get("entries", []))


async def add(guild: discord.Guild, text: str) -> bool:
    text = text.strip()[:MAX_LEN]
    if not text:
        return False
    s, entries = await _load(guild)
    entries.append(text)
    await s.set(NS, {"entries": entries[-MAX_ENTRIES:]})
    return True


async def entries(guild: discord.Guild) -> list[str]:
    _s, e = await _load(guild)
    return e


async def clear(guild: discord.Guild) -> None:
    s, _ = await _load(guild)
    await s.set(NS, {"entries": []})


async def get_text(guild: discord.Guild) -> str:
    e = await entries(guild)
    return "\n".join(f"- {x}" for x in e)
