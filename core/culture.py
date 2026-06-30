"""Learn the server's collective communication style so Zafven blends in.

Samples recent public messages and distills an AGGREGATE style digest (tone,
slang, energy, humour, formality) — never per-person profiling, never quoting or
mimicking an individual, and never adopting toxic/slur/NSFW usage as 'style'.
Stored per guild via the Discord-backed store; refreshed on a schedule.
"""
from __future__ import annotations

import logging
import time

import discord

from core import store
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.culture")

NS = "culture"
SAMPLE = 180

_PROFILER = (
    "You are profiling a Discord server's COLLECTIVE communication style so a chat bot can blend in. "
    "From the message sample, summarize ONLY the shared style: overall tone, energy level, the slang / "
    "catchphrases they actually use, kind of humour, formality, and emoji habits. "
    "AGGREGATE ONLY — never name, quote, describe, or imitate any specific person. "
    "Do NOT report hateful language, slurs, or NSFW as style to adopt. Output 4-6 short lines."
)


async def get_digest(guild: discord.Guild) -> str:
    s = await store.get_store(guild)
    return (s.get(NS, {}) or {}).get("digest", "")


async def build_digest(bot, guild: discord.Guild) -> bool:
    snippets: list[str] = []
    for ch in guild.text_channels:
        if len(snippets) >= SAMPLE or not ch.permissions_for(guild.me).read_message_history:
            continue
        try:
            async for msg in ch.history(limit=60):
                if msg.author.bot or not msg.content.strip():
                    continue
                snippets.append(msg.content)
                if len(snippets) >= SAMPLE:
                    break
        except discord.HTTPException:
            continue
    if len(snippets) < 20:
        return False

    corpus = "\n".join(snippets)[:40000]
    try:
        digest = await bot.gateway.narrate(  # type: ignore[attr-defined]
            _PROFILER, f"Server message sample:\n{corpus}", web_search=False, max_tokens=400)
    except GatewayError as exc:
        log.warning("culture digest failed in %s: %s", guild.name, exc)
        return False

    s = await store.get_store(guild)
    await s.set(NS, {"digest": digest, "ts": time.time()})
    log.info("Refreshed culture digest for %s", guild.name)
    return True
