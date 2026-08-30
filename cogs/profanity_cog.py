"""Auto-moderates banned language: curse words, hate slurs, and sexual slang.

On a match the bot deletes the message and posts a short auto-deleting notice that
names what was wrong and asks the member to correct themselves. Each match is a
**strike**. Strikes are persisted per guild (they survive restarts) and expire
after a rolling window (default 1 hour); reach the limit (default 3) inside that
window and the member is timed out (default 15 minutes) and their strikes reset.

Mods can inspect or wipe a member's strikes with `/strikes check` and
`/strikes clear`. Needs **Manage Messages** (to delete) and **Moderate Members**
(to time out). Members with Manage Messages are exempt when PROFANITY_BYPASS_MODS
is true.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import profanity, strikes


log = logging.getLogger("zafven.profanity")


class ProfanityCog(commands.Cog):
    strikes_group = app_commands.Group(
        name="strikes", description="Check or clear a member's language strikes (mods).",
        default_permissions=discord.Permissions(manage_messages=True))

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

        # Persist the strike (survives restarts). If the store hiccups, treat it as
        # a first strike so we still warn rather than silently swallowing it.
        try:
            live = await strikes.add(message.guild.id, message.author.id,
                                     config.PROFANITY_STRIKE_WINDOW_SECONDS)
        except Exception:  # noqa: BLE001 — moderation must not break on store errors
            log.exception("strike persistence failed")
            live = 1

        limit = max(1, config.PROFANITY_STRIKE_LIMIT)
        if live >= limit:
            await self._mute(message, what)
            try:
                await strikes.clear(message.guild.id, message.author.id)
            except Exception:  # noqa: BLE001
                log.exception("strike reset failed")
        else:
            await self._warn(message, what, live, limit)

    async def _warn(self, message: discord.Message, what: str, live: int, limit: int) -> None:
        mins = max(1, config.PROFANITY_MUTE_SECONDS // 60)
        try:
            note = await message.channel.send(
                f"🚫 {message.author.mention}, your message was removed for **{what}**. "
                f"please correct yourself and keep it respectful — **strike {live}/{limit}** "
                f"this hour. hit {limit} and you're muted for {mins} minutes."
            )
            await note.delete(delay=10)
        except discord.HTTPException:
            pass
        log.info("Profanity strike %d/%d for %s (%s)", live, limit, message.author, what)

    async def _mute(self, message: discord.Message, what: str) -> None:
        guild = message.guild
        me = guild.me
        mins = max(1, config.PROFANITY_MUTE_SECONDS // 60)
        member = message.author
        limit = max(1, config.PROFANITY_STRIKE_LIMIT)
        muted = False
        if (isinstance(member, discord.Member) and me.guild_permissions.moderate_members
                and member.top_role < me.top_role and member.id != guild.owner_id):
            try:
                await member.timeout(
                    timedelta(seconds=config.PROFANITY_MUTE_SECONDS),
                    reason=f"zafven: {limit} language strikes in an hour ({what})")
                muted = True
            except discord.HTTPException as exc:
                log.warning("Could not timeout %s: %s", member, exc)

        try:
            if muted:
                await message.channel.send(
                    f"🔇 {member.mention} hit **{limit} strikes** this hour and has been muted for "
                    f"**{mins} minutes**. come back ready to keep it clean.")
            else:
                await message.channel.send(
                    f"🚫 {member.mention}, that's **{limit} strikes** — I couldn't mute you, so a "
                    "human mod will follow up.")
        except discord.HTTPException:
            pass
        log.info("Profanity mute (%d strikes) for %s (%s), muted=%s", limit, member, what, muted)

    # ── mod commands ─────────────────────────────────────────────────────
    @strikes_group.command(name="check", description="See a member's current language strikes.")
    @app_commands.describe(member="Whose strikes to check.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def check(self, interaction: discord.Interaction, member: discord.Member) -> None:
        n = await strikes.count(interaction.guild, member.id, config.PROFANITY_STRIKE_WINDOW_SECONDS)
        limit = max(1, config.PROFANITY_STRIKE_LIMIT)
        mins = max(1, config.PROFANITY_STRIKE_WINDOW_SECONDS // 60)
        await interaction.response.send_message(
            f"📋 {member.mention} has **{n}/{limit}** language strike(s) in the last {mins} minutes.",
            ephemeral=True)

    @strikes_group.command(name="clear", description="Wipe a member's language strikes.")
    @app_commands.describe(member="Whose strikes to clear.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction, member: discord.Member) -> None:
        had = await strikes.clear(interaction.guild, member.id)
        msg = (f"🧹 Cleared {member.mention}'s language strikes." if had
               else f"{member.mention} had no active strikes.")
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfanityCog(bot))
