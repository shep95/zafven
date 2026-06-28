"""Anti-cyberbullying: warn once, then mute for 30 minutes if it continues.

On a detected harassment message the bot deletes it and @mentions the author with
a warning. If the SAME author harasses again while that warning is still active,
they're timed out for HARASS_MUTE_SECONDS. Needs Manage Messages + Moderate
Members. Mods are exempt by default.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import discord
from discord.ext import commands

import config
from core import harassment

log = logging.getLogger("zafven.antiharass")


class AntiHarassCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # (guild_id, user_id) -> timestamp until which a warning stays "active"
        self._warned_until: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.HARASS_FILTER_ENABLED:
            return
        if message.author.bot or message.guild is None or not message.content:
            return
        member = message.author
        if config.HARASS_BYPASS_MODS and isinstance(member, discord.Member) \
                and member.guild_permissions.manage_messages:
            return

        category = harassment.detect(message.content)
        if not category:
            return

        # Always remove the offending message if we can.
        if message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        key = (message.guild.id, member.id)
        now = time.time()
        active = self._warned_until.get(key, 0) > now

        if active:
            await self._mute(message, member, category)
            self._warned_until.pop(key, None)
        else:
            self._warned_until[key] = now + config.HARASS_WARN_WINDOW_SECONDS
            await self._warn(message, member, category)

    async def _warn(self, message: discord.Message, member: discord.abc.User, category: str) -> None:
        mins = config.HARASS_MUTE_SECONDS // 60
        try:
            await message.channel.send(
                f"⚠️ {member.mention} — that reads as **{category}**. Stop now, or you'll be "
                f"muted for {mins} minutes if it continues.")
        except discord.HTTPException:
            pass
        log.info("Harassment warning issued to %s (%s)", member, category)

    async def _mute(self, message: discord.Message, member: discord.abc.User, category: str) -> None:
        guild = message.guild
        me = guild.me
        mins = config.HARASS_MUTE_SECONDS // 60
        if (isinstance(member, discord.Member) and me.guild_permissions.moderate_members
                and member.top_role < me.top_role and member.id != guild.owner_id):
            try:
                await member.timeout(timedelta(seconds=config.HARASS_MUTE_SECONDS),
                                     reason=f"zafven anti-harassment: {category} after warning")
                await message.channel.send(
                    f"🔇 {member.mention} has been muted for {mins} minutes for continued harassment.")
                log.info("Muted %s for harassment (%s)", member, category)
                return
            except discord.HTTPException as exc:
                log.warning("Could not timeout %s: %s", member, exc)
        # Couldn't mute (perms/hierarchy) — at least flag it.
        try:
            await message.channel.send(
                f"🚫 {member.mention}, that's a final warning — I couldn't mute you, a human mod will follow up.")
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiHarassCog(bot))
