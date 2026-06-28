"""/mood — an aggregate read of the server's current vibe.

Aggregate ONLY: it samples recent public messages and reports the room's overall
mood/energy. It never names, quotes, or profiles any individual.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.mood")

SAMPLE = 200


class MoodCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="mood", description="Read the server's current collective vibe (aggregate).")
    @app_commands.guild_only()
    async def mood(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        snippets: list[str] = []
        for ch in guild.text_channels:
            if len(snippets) >= SAMPLE or not ch.permissions_for(guild.me).read_message_history:
                continue
            try:
                async for msg in ch.history(limit=50):
                    if msg.author.bot or not msg.content.strip():
                        continue
                    snippets.append(msg.content)
                    if len(snippets) >= SAMPLE:
                        break
            except discord.HTTPException:
                continue

        if len(snippets) < 15:
            await interaction.followup.send("Not enough recent chatter to read the mood.")
            return

        corpus = "\n".join(snippets)[:45000]
        system = (f"{load_brain('persona')}\n\nRead the AGGREGATE mood/energy of a community from a "
                  "sample of recent messages. Give a short 'frequency report': overall tone, themes, "
                  "energy level. NEVER name, quote, or single out any individual — themes only.")
        try:
            text = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, f"Read the collective mood:\n\n{corpus}", web_search=False, max_tokens=600)
        except GatewayError as exc:
            log.warning("mood failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now.")
            return

        embed = discord.Embed(title="🌡️ Server Mood Index", description=text[:4000],
                              color=discord.Color.blurple())
        embed.set_footer(text=f"Aggregate of {len(snippets)} recent messages • no individuals named")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MoodCog(bot))
