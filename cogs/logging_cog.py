"""Welcome card on join + leave log. Welcome goes to WELCOME_CHANNEL, leave to MEMBER_LOG_CHANNEL."""
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

    async def _get_channel(self, guild: discord.Guild, name: str) -> discord.TextChannel | None:
        existing = discord.utils.get(guild.text_channels, name=name)
        if existing:
            return existing
        if not guild.me.guild_permissions.manage_channels:
            log.warning("No '%s' channel and missing Manage Channels in %s", name, guild.name)
            return None
        try:
            channel = await guild.create_text_channel(name, reason="zafven member channel")
            log.info("Created #%s in %s", channel.name, guild.name)
            return channel
        except discord.HTTPException as exc:
            log.warning("Could not create #%s: %s", name, exc)
            return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        channel = await self._get_channel(member.guild, config.WELCOME_CHANNEL)
        if not channel:
            return
        guild = member.guild
        created = member.created_at
        age_days = (datetime.now(timezone.utc) - created).days
        joined_ts = int((member.joined_at or datetime.now(timezone.utc)).timestamp())

        embed = discord.Embed(
            title=f"🎉 Welcome {member.display_name} to {guild.name}!",
            description=f"We're glad to have you here, {member.mention} !",
            color=discord.Color.brand_green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 Username", value=str(member))
        embed.add_field(name="🆔 User ID", value=f"`{member.id}`")
        embed.add_field(name="🤖 Is Bot?", value="Yes" if member.bot else "No")
        embed.add_field(name="📅 Account Created",
                        value=f"<t:{int(created.timestamp())}:D>\n(<t:{int(created.timestamp())}:R>)")
        embed.add_field(name="🕐 Joined Server", value=f"<t:{joined_ts}:D>\n<t:{joined_ts}:t>")
        embed.add_field(name="👥 Server Members",
                        value=f"Joining {max(guild.member_count - 1, 0)} other members in {guild.name}!",
                        inline=False)
        if age_days < 7:
            embed.add_field(name="⚠️ Heads up", value="Brand-new account — keep an eye out.", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{guild.member_count} | {guild.name}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        channel = await self._get_channel(member.guild, config.MEMBER_LOG_CHANNEL)
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
