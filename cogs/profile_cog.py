"""/profile — a public psychological breakdown of a member from their messages.

Built from the target's own public messages, posted publicly with @mention so they
see it. Anyone with an opt-out role (PROFILE_OPTOUT_ROLES) cannot be profiled.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import psych_profile

log = logging.getLogger("zafven.profile")


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="profile",
        description="Public psychological breakdown of a member from their chat history.",
    )
    @app_commands.describe(
        member="The member to break down (they'll see it).",
        focus="Optional angle, e.g. 'their conflict style' or 'why they're passive-aggressive'.",
    )
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: discord.Member,
                      focus: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        embed, err = await psych_profile.run_breakdown(
            self.bot.gateway, interaction.guild, member, focus=focus or "")  # type: ignore[arg-type]
        if err:
            await interaction.followup.send(err)
            return
        await interaction.followup.send(content=member.mention, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
