"""Zafven's chat memory — short notes about people, from what they tell her.

Notes shared with Zafven are stored in user-scoped SQLite state and mirrored to
private personal channels. Legacy shared-channel notes migrate on first access.
Users inspect (/memory) and reset (/forget) their own active state.
"""
from __future__ import annotations

import discord
import logging

from core import store
from core.user_memory import memory

NS = "chat_memory"
MAX_NOTE_LEN = 200


async def _load(guild: discord.Guild) -> tuple[object, dict]:
    s = await store.get_store(guild)
    table = dict(s.get(NS, {}) or {})
    return s, table


async def get_notes(guild: discord.Guild, user_id: int) -> list[str]:
    return list((await memory.load(guild, user_id))["notes"])


async def add_note(guild: discord.Guild, user_id: int, note: str) -> None:
    note = note.strip()[:MAX_NOTE_LEN]
    if not note:
        return
    await memory.load(guild, user_id)
    await memory.add(guild.id, user_id, "notes", note)


async def clear(guild: discord.Guild, user_id: int) -> bool:
    await memory.load(guild, user_id)
    await memory.clear(guild.id, user_id)
    # Also remove the older shared-channel copy, if still present.
    try:
        s, table = await _load(guild)
        if str(user_id) in table:
            table.pop(str(user_id))
            await s.set(NS, table)
    except Exception:
        logging.getLogger("zafven.memory").exception(
            "Active memory reset succeeded; legacy-channel cleanup unavailable")
    return True
