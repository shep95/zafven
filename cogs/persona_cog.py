"""/persona — admins tune how Zafven acts (style only; safety stays locked)."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import persona

log = logging.getLogger("zafven.persona")


class PersonaCog(commands.Cog):
    group = app_commands.Group(
        name="persona", description="Tune how Zafven acts (admins).",
        default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @group.command(name="set", description="Adjust Zafven's style/tone for this server.")
    @app_commands.describe(directive="How she should act, e.g. 'be concise, fewer emojis, more formal'.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def set(self, interaction: discord.Interaction, directive: str) -> None:
        await persona.set_directive(interaction.guild, directive)
        embed = discord.Embed(
            title="🎭 Persona updated",
            description=f"Zafven will adjust her style to:\n> {directive[:1000]}",
            color=discord.Color.purple())
        embed.set_footer(text="Style only — her safety boundaries can't be changed.")
        await interaction.response.send_message(embed=embed)
        log.info("Persona set in %s by %s", interaction.guild.name, interaction.user)

    @group.command(name="view", description="Show Zafven's current custom style.")
    @app_commands.guild_only()
    async def view(self, interaction: discord.Interaction) -> None:
        directive = await persona.get_directive(interaction.guild)
        msg = f"Current style directive:\n> {directive}" if directive else "No custom style set — she's her default self."
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="reset", description="Reset Zafven to her default personality.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reset(self, interaction: discord.Interaction) -> None:
        await persona.clear(interaction.guild)
        await interaction.response.send_message("🎭 Reset — Zafven is back to her default self.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PersonaCog(bot))
