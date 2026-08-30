"""Auto-moderates banned language: curse words, hate slurs, and sexual slang.

On a match the bot deletes the message and posts a short auto-deleting notice that
names what was wrong and asks the member to correct themselves. Each match is a
**strike**. Strikes expire after a rolling window (default 1 hour); reach the limit
(default 3) inside that window and the member is timed out (default 15 minutes) and
their strike count resets.

Needs **Manage Messages** (to delete) and **Moderate Members** (to time out).
Members with Manage Messages are exempt when PROFANITY_BYPASS_MODS is true.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import discord
from discord.ext import commands

import config
from core import profanity

log = logging.getLogger("zafven.profanity")


class ProfanityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        profanity.refresh()
        # (guild_id, user_id) -> list of strike timestamps within the window
        self._strikes: dict[tuple[int, int], list[float]] = {}

    def _add_strike(self, guild_id: int, user_id: int) -> int:
        """Record a strike now, drop expired ones, return the live strike count."""
        key = (guild_id, user_id)
        now = time.time()
        window = max(1, config.PROFANITY_STRIKE_WINDOW_SECONDS)
        recent = [t for t in self._strikes.get(key, []) if now - t < window]
        recent.append(now)
        self._strikes[key] = recent
        return len(recent)

    def _reset_strikes(self, guild_id: int, user_id: int) -> None:
        self._strikes.pop((guild_id, user_id), None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.PROFANITY_FILTER_ENABLED:
            return
        if message.author.bot or message.guild is None or not message.content:
            return
        if config.PROFANITY_BYPASS_MODS and isinstance(message.author, discord.Member):
            if message.author.guild_permissions.manage_messages:
                return

        if profanity.count(message.content) < config.PROFANITY_THRESHOLD:
            return

        what = profanity.describe(message.content)
        me = message.guild.me

        # Always remove the offending message if we can.
        if message.channel.permissions_for(me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        else:
            log.warning("Banned language in #%s but I lack Manage Messages.", message.channel)

        strikes = self._add_strike(message.guild.id, message.author.id)
        limit = max(1, config.PROFANITY_STRIKE_LIMIT)

        if strikes >= limit:
            await self._mute(message, what)
            self._reset_strikes(message.guild.id, message.author.id)
        else:
            await self._warn(message, what, strikes, limit)

    async def _warn(self, message: discord.Message, what: str, strikes: int, limit: int) -> None:
        mins = max(1, config.PROFANITY_MUTE_SECONDS // 60)
        try:
            note = await message.channel.send(
                f"🚫 {message.author.mention}, your message was removed for **{what}**. "
                f"please correct yourself and keep it respectful — **strike {strikes}/{limit}** "
                f"this hour. hit {limit} and you're muted for {mins} minutes."
            )
            await note.delete(delay=10)
        except discord.HTTPException:
            pass
        log.info("Profanity strike %d/%d for %s (%s)", strikes, limit, message.author, what)

    async def _mute(self, message: discord.Message, what: str) -> None:
        guild = message.guild
        me = guild.me
        mins = max(1, config.PROFANITY_MUTE_SECONDS // 60)
        member = message.author
        muted = False
        if (isinstance(member, discord.Member) and me.guild_permissions.moderate_members
                and member.top_role < me.top_role and member.id != guild.owner_id):
            try:
                await member.timeout(
                    timedelta(seconds=config.PROFANITY_MUTE_SECONDS),
                    reason=f"zafven: {config.PROFANITY_STRIKE_LIMIT} language strikes in an hour ({what})")
                muted = True
            except discord.HTTPException as exc:
                log.warning("Could not timeout %s: %s", member, exc)

        try:
            if muted:
                await message.channel.send(
                    f"🔇 {member.mention} hit **{config.PROFANITY_STRIKE_LIMIT} strikes** this hour "
                    f"and has been muted for **{mins} minutes**. come back ready to keep it clean.")
            else:
                await message.channel.send(
                    f"🚫 {member.mention}, that's **{config.PROFANITY_STRIKE_LIMIT} strikes** — "
                    "I couldn't mute you, so a human mod will follow up.")
        except discord.HTTPException:
            pass
        log.info("Profanity mute (%s strikes) for %s (%s), muted=%s",
                 config.PROFANITY_STRIKE_LIMIT, member, what, muted)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfanityCog(bot))
