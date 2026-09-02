"""Invite tracking + referral leaderboard, persisted per guild via the store.

Two tables:
  * counts   — {user_id: how many members they've brought in}
  * personal — {user_id: their personal invite code} (so /invite is stable)
"""
from __future__ import annotations

import discord

from core import store

NS_COUNTS = "invite_counts"
NS_PERSONAL = "invite_personal"


async def add_credit(guild: discord.Guild, user_id: int, n: int = 1) -> int:
    s = await store.get_store(guild)
    table = dict(s.get(NS_COUNTS, {}) or {})
    new = int(table.get(str(user_id), 0)) + n
    table[str(user_id)] = new
    await s.set(NS_COUNTS, table)
    return new


async def get_count(guild: discord.Guild, user_id: int) -> int:
    s = await store.get_store(guild)
    return int((s.get(NS_COUNTS, {}) or {}).get(str(user_id), 0))


async def all_counts(guild: discord.Guild) -> dict[int, int]:
    s = await store.get_store(guild)
    return {int(k): int(v) for k, v in (s.get(NS_COUNTS, {}) or {}).items()}


async def leaderboard(guild: discord.Guild, limit: int = 10) -> list[tuple[int, int]]:
    counts = await all_counts(guild)
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]


async def get_personal(guild: discord.Guild, user_id: int) -> str | None:
    s = await store.get_store(guild)
    return (s.get(NS_PERSONAL, {}) or {}).get(str(user_id))


async def set_personal(guild: discord.Guild, user_id: int, code: str) -> None:
    s = await store.get_store(guild)
    table = dict(s.get(NS_PERSONAL, {}) or {})
    table[str(user_id)] = code
    await s.set(NS_PERSONAL, table)


async def owner_of_code(guild: discord.Guild, code: str) -> int | None:
    """Reverse-lookup: which member owns this personal invite code."""
    s = await store.get_store(guild)
    for uid, c in (s.get(NS_PERSONAL, {}) or {}).items():
        if c == code:
            try:
                return int(uid)
            except (TypeError, ValueError):
                return None
    return None
