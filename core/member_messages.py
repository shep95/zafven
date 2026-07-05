"""Collect a member's recent public messages for vibe / psych reads."""
from __future__ import annotations

import discord

MAX_MESSAGES = 80
PER_CHANNEL_SCAN = 400


async def collect(guild: discord.Guild, member: discord.abc.User, *,
                  limit: int = MAX_MESSAGES) -> list[str]:
    collected: list[str] = []
    for channel in guild.text_channels:
        if len(collected) >= limit:
            break
        perms = channel.permissions_for(guild.me)
        if not (perms.read_message_history and perms.view_channel):
            continue
        try:
            async for msg in channel.history(limit=PER_CHANNEL_SCAN):
                if msg.author.id == member.id and msg.content.strip():
                    collected.append(msg.content)
                    if len(collected) >= limit:
                        break
        except discord.HTTPException:
            continue
    return collected
