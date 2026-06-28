"""Zafven's chat memory — short notes about people, from what they tell her.

Consensual by design: it only stores things a user shares *with Zafven in chat*.
It is NOT a profile harvested from the server, and it never stores facts about
third parties. Persisted per-guild via the Discord-backed store. Users can view
(`/memory`) and wipe (`/forget`) their own notes.
"""
from __future__ import annotations

import discord

from core import store

NS = "chat_memory"
MAX_NOTES = 15
MAX_NOTE_LEN = 200


async def _load(guild: discord.Guild) -> tuple[object, dict]:
    s = await store.get_store(guild)
    table = dict(s.get(NS, {}) or {})
    return s, table


async def get_notes(guild: discord.Guild, user_id: int) -> list[str]:
    _s, table = await _load(guild)
    return list(table.get(str(user_id), []))


async def add_note(guild: discord.Guild, user_id: int, note: str) -> None:
    note = note.strip()[:MAX_NOTE_LEN]
    if not note:
        return
    s, table = await _load(guild)
    notes = table.get(str(user_id), [])
    if note.lower() in (n.lower() for n in notes):
        return
    notes.append(note)
    table[str(user_id)] = notes[-MAX_NOTES:]
    await s.set(NS, table)


async def clear(guild: discord.Guild, user_id: int) -> bool:
    s, table = await _load(guild)
    if str(user_id) in table:
        table.pop(str(user_id))
        await s.set(NS, table)
        return True
    return False
