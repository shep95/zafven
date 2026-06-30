"""Refreshes the server's culture/style digest on a schedule; /culture to manage."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import culture

log = logging.getLogger("zafven.culture")


class CultureCog(commands.Cog):
    group = app_commands.Group(
        name="culture", description="How Zafven adapts to the server's vibe (admins).",
        default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        if config.CULTURE_ADAPT_ENABLED:
            self.refresh.change_interval(hours=max(1, config.CULTURE_REFRESH_HOURS))
            self.refresh.start()

    def cog_unload(self) -> None:
        self.refresh.cancel()

    @tasks.loop(hours=12)
    async def refresh(self) -> None:
        for guild in list(self.bot.guilds):
            try:
                await culture.build_digest(self.bot, guild)
            except Exception:  # noqa: BLE001
                log.exception("culture refresh failed for %s", guild)

    @refresh.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    @group.command(name="refresh", description="Re-learn the server's vibe now.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def refresh_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        ok = await culture.build_digest(self.bot, interaction.guild)
        await interaction.followup.send(
            "✅ Re-learned the vibe." if ok else "Not enough recent chatter to read the vibe yet.",
            ephemeral=True)

    @group.command(name="view", description="See the vibe Zafven has picked up.")
    @app_commands.guild_only()
    async def view(self, interaction: discord.Interaction) -> None:
        digest = await culture.get_digest(interaction.guild)
        await interaction.response.send_message(
            f"🌀 Server vibe I've picked up:\n>>> {digest}" if digest else "I haven't read the vibe yet.",
            ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CultureCog(bot))
