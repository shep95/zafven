"""Bot-owner identity + a global 'protect-list' for the bot's own moderation.

Two honest, buildable capabilities:

  • is_owner() — the hardcoded bot creator (config.OWNER_ID). Owner-only commands
    live in cogs/owner_cog.py.

  • a global protect-list — accounts the bot's OWN auto-moderation (profanity,
    anti-spam, anti-harassment, anti-manipulation) will never action, in every
    server the bot is in. The owner is always implicitly protected.

What this deliberately does NOT do: it cannot stop a server's own human admins
from using Discord's native mute/kick/ban, and it cannot override another server's
owner. A bot can never outrank a server owner (they can remove it in one click),
so the only thing it can honestly guarantee is its own behaviour — which is what
the protect-list governs. The list is loaded once into memory and consulted
synchronously by the moderation cogs.
"""
from __future__ import annotations

import logging

import config

log = logging.getLogger("zafven.owner")

_NS = "owner_protect"          # {"ids": [int, ...]} in the home-guild store
_protected: set[int] = set()   # in-memory cache, loaded on ready
_loaded = False


def is_owner(user_id: int) -> bool:
    return int(user_id) == config.OWNER_ID


def is_protected(user_id: int) -> bool:
    """True if the user is the owner or on the global protect-list — i.e. the bot's
    own auto-moderation must leave them alone."""
    uid = int(user_id)
    return uid == config.OWNER_ID or uid in _protected


def protected_ids() -> list[int]:
    return sorted(_protected)


async def load(store: object) -> None:
    """Populate the in-memory protect-list from the home-guild store (once)."""
    global _loaded
    data = store.get(_NS, {}) or {}  # type: ignore[attr-defined]
    _protected.clear()
    for uid in data.get("ids", []):
        try:
            _protected.add(int(uid))
        except (TypeError, ValueError):
            continue
    _loaded = True
    log.info("owner protect-list loaded: %d account(s)", len(_protected))


async def add_protected(store: object, user_id: int) -> bool:
    uid = int(user_id)
    if uid in _protected:
        return False
    _protected.add(uid)
    await _save(store)
    return True


async def remove_protected(store: object, user_id: int) -> bool:
    uid = int(user_id)
    if uid not in _protected:
        return False
    _protected.discard(uid)
    await _save(store)
    return True


async def _save(store: object) -> None:
    await store.set(_NS, {"ids": sorted(_protected)})  # type: ignore[attr-defined]
