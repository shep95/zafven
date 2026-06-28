"""Compute member activity by scanning Discord message history (no database)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

log = logging.getLogger("zafven.activity")


@dataclass
class InactiveMember:
    member: discord.Member
    last_active: datetime | None


async def scan_last_active(guild: discord.Guild, scan_limit: int) -> dict[int, datetime]:
    last_active: dict[int, datetime] = {}
    for channel in guild.text_channels:
        perms = channel.permissions_for(guild.me)
        if not (perms.read_message_history and perms.view_channel):
            continue
        try:
            async for msg in channel.history(limit=scan_limit):
                if msg.author.bot:
                    continue
                prev = last_active.get(msg.author.id)
                if prev is None or msg.created_at > prev:
                    last_active[msg.author.id] = msg.created_at
        except discord.Forbidden:
            continue
        except discord.HTTPException as exc:
            log.warning("History scan failed in #%s: %s", channel.name, exc)
    return last_active


async def find_inactive(guild: discord.Guild, inactive_days: int, scan_limit: int,
                        protected_roles: list[str], join_grace_days: int) -> list[InactiveMember]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=inactive_days)
    grace_cutoff = now - timedelta(days=join_grace_days)
    protected = {r.lower() for r in protected_roles}

    last_active = await scan_last_active(guild, scan_limit)
    results: list[InactiveMember] = []
    for member in guild.members:
        if member.bot or member.id == guild.owner_id:
            continue
        if any(role.name.lower() in protected for role in member.roles):
            continue
        if member.joined_at and member.joined_at > grace_cutoff:
            continue
        seen = last_active.get(member.id)
        if seen is None or seen < cutoff:
            results.append(InactiveMember(member=member, last_active=seen))

    results.sort(key=lambda im: (im.last_active or datetime.min.replace(tzinfo=timezone.utc)))
    return results
