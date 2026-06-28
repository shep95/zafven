"""Logs members joining and leaving to a dedicated channel."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config

log = logging.getLogger("zafven.logging")


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _get_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        existing = discord.utils.get(guild.text_channels, name=config.MEMBER_LOG_CHANNEL)
        if existing:
            return existing
        me = guild.me
        if not me.guild_permissions.manage_channels:
            log.warning("No '%s' channel and missing Manage Channels in %s",
                        config.MEMBER_LOG_CHANNEL, guild.name)
            return None
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=False),
                me: discord.PermissionOverwrite(send_messages=True, view_channel=True),
            }
            channel = await guild.create_text_channel(
                config.MEMBER_LOG_CHANNEL, overwrites=overwrites, reason="zafven member log")
            log.info("Created log channel #%s in %s", channel.name, guild.name)
            return channel
        except discord.HTTPException as exc:
            log.warning("Could not create log channel: %s", exc)
            return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        channel = await self._get_log_channel(member.guild)
        if not channel:
            return
        created = member.created_at
        age_days = (datetime.now(timezone.utc) - created).days
        embed = discord.Embed(
            title="📥 Member Joined", description=f"{member.mention} ({member})",
            color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Account created",
                        value=f"<t:{int(created.timestamp())}:R> ({age_days}d old)")
        embed.add_field(name="Member count", value=str(member.guild.member_count))
        if age_days < 7:
            embed.add_field(name="⚠️ Note", value="Brand-new account", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        channel = await self._get_log_channel(member.guild)
        if not channel:
            return
        joined = member.joined_at
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed = discord.Embed(
            title="📤 Member Left", description=f"{member} left the server",
            color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
        if joined:
            stayed = (datetime.now(timezone.utc) - joined).days
            embed.add_field(name="Joined", value=f"<t:{int(joined.timestamp())}:R> ({stayed}d ago)")
        embed.add_field(name="Member count", value=str(member.guild.member_count))
        if roles:
            embed.add_field(name="Roles", value=" ".join(roles[:10]), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id}")
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
