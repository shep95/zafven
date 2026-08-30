"""Persistent profanity strikes — survives restarts via the Discord-backed store.

Each guild keeps a table of {user_id: [strike_timestamps]}. Strikes older than the
rolling window are pruned on every read/write, so a member is only muted for
strikes clustered inside the window. Writes happen only on a violation (rare), so
the per-event store write is cheap enough.
"""
from __future__ import annotations

import time

import discord

from core import store

NS = "profanity_strikes"


async def _load(guild: discord.Guild) -> tuple[object, dict]:
    s = await store.get_store(guild)
    return s, dict(s.get(NS, {}) or {})


def _prune(timestamps: list[float], window: int, now: float) -> list[float]:
    return [t for t in timestamps if now - t < window]


async def add(guild: discord.Guild, user_id: int, window: int) -> int:
    """Record a strike now, drop expired ones, persist, and return the live count."""
    s, table = await _load(guild)
    now = time.time()
    recent = _prune(table.get(str(user_id), []), max(1, window), now)
    recent.append(now)
    table[str(user_id)] = recent
    await s.set(NS, table)
    return len(recent)


async def count(guild: discord.Guild, user_id: int, window: int) -> int:
    """Current live strike count for a member (read-only; prunes for the count)."""
    _s, table = await _load(guild)
    return len(_prune(table.get(str(user_id), []), max(1, window), time.time()))


async def clear(guild: discord.Guild, user_id: int) -> bool:
    """Wipe a member's strikes. Returns True if they had any."""
    s, table = await _load(guild)
    if str(user_id) in table:
        table.pop(str(user_id))
        await s.set(NS, table)
        return True
    return False
