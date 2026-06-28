"""Shared mod-alert plumbing: the alert channel + an @mention for moderators."""
from __future__ import annotations

import discord

import config


def mod_roles(guild: discord.Guild) -> list[discord.Role]:
    wanted = {r.lower() for r in config.MOD_ROLES}
    return [r for r in guild.roles if r.name.lower() in wanted]


def mod_ping(guild: discord.Guild) -> tuple[str | None, discord.AllowedMentions | None]:
    """Content string + allowed_mentions that actually ping the mod roles."""
    roles = mod_roles(guild)
    if not roles:
        return None, None
    return " ".join(r.mention for r in roles), discord.AllowedMentions(roles=roles)


async def get_alert_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Find or create the (hidden, mod-visible) mod-alerts channel."""
    existing = discord.utils.get(guild.text_channels, name=config.MOD_ALERT_CHANNEL)
    if existing:
        return existing
    me = guild.me
    if not me.guild_permissions.manage_channels:
        return None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    for role in mod_roles(guild):
        overwrites[role] = discord.PermissionOverwrite(view_channel=True)
    try:
        return await guild.create_text_channel(
            config.MOD_ALERT_CHANNEL, overwrites=overwrites, reason="zafven mod alerts")
    except discord.HTTPException:
        return None


async def send_alert(guild: discord.Guild, embed: discord.Embed) -> None:
    """Post an embed to the mod-alerts channel, pinging the mod roles."""
    channel = await get_alert_channel(guild)
    if channel is None:
        return
    content, allowed = mod_ping(guild)
    try:
        await channel.send(content=content, embed=embed, allowed_mentions=allowed)
    except discord.HTTPException:
        pass
