"""Auto-censors curse words in messages.

When a message has >= PROFANITY_THRESHOLD profane words, the bot either deletes
it ("delete") or deletes and reposts a starred version ("censor"). Needs the
Manage Messages permission; without it, it logs and does nothing.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from core import profanity

log = logging.getLogger("zafven.profanity")


class ProfanityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        profanity.refresh()

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

        me = message.guild.me
        if not message.channel.permissions_for(me).manage_messages:
            log.warning("Profanity match in #%s but I lack Manage Messages.", message.channel)
            return

        try:
            await message.delete()
        except discord.HTTPException:
            return

        if config.PROFANITY_ACTION == "delete":
            await self._warn(message)
            return

        # "censor": repost the cleaned message attributed to the author.
        cleaned = profanity.censor(message.content)
        try:
            await message.channel.send(f"🔇 **{message.author.display_name}:** {cleaned}"[:2000])
        except discord.HTTPException:
            pass

    async def _warn(self, message: discord.Message) -> None:
        try:
            note = await message.channel.send(
                f"🔇 {message.author.mention}, please keep it clean.")
            await note.delete(delay=5)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfanityCog(bot))
