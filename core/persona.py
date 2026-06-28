"""Per-server persona overlay — how the server wants Zafven to act.

Admins set a style directive (tone, verbosity, emoji use, formality, quirks) that
is folded into her chat personality. It adjusts *style*, never her safety
boundaries. Persisted via the Discord-backed store so it survives restarts.
"""
from __future__ import annotations

import discord

from core import store

NS = "persona"
MAX_LEN = 1000


async def get_directive(guild: discord.Guild) -> str:
    s = await store.get_store(guild)
    data = s.get(NS, {}) or {}
    return data.get("directive", "")


async def set_directive(guild: discord.Guild, text: str) -> None:
    s = await store.get_store(guild)
    await s.set(NS, {"directive": text.strip()[:MAX_LEN]})


async def clear(guild: discord.Guild) -> None:
    s = await store.get_store(guild)
    await s.set(NS, {})
