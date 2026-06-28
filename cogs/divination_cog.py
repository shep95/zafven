"""/tarot, /iching, /dream — symbolic draws narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import divination
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.divination")


class DivinationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _read(self, interaction: discord.Interaction, title: str, facts: str,
                    color: discord.Color) -> None:
        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("divination"), facts, web_search=False, max_tokens=900)
        except GatewayError as exc:
            log.warning("divination failed: %s", exc)
            await interaction.followup.send("🔌 The oracle is unreachable right now. Try again shortly.")
            return
        embed = discord.Embed(title=title, description=reading[:4000], color=color)
        embed.set_footer(text="zafven • for reflection & entertainment")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="tarot", description="Draw a tarot spread and have it read.")
    @app_commands.describe(question="Optional focus for the reading.",
                           cards="How many cards (1-5). Default 3.")
    async def tarot(self, interaction: discord.Interaction, question: str | None = None,
                    cards: int = 3) -> None:
        await interaction.response.defer(thinking=True)
        draw = divination.draw_tarot(count=max(1, min(cards, 5)))
        drawn = "\n".join(f"- {n}{' (reversed)' if rev else ''}: {m}" for n, m, rev in draw.cards)
        facts = (f"Tarot spread{f' on: {question}' if question else ''}:\n{drawn}\n"
                 "Read these cards in order as one short story + a takeaway.")
        await self._read(interaction, "🃏 Tarot", facts, discord.Color.dark_gold())

    @app_commands.command(name="iching", description="Cast the I Ching and have it read.")
    @app_commands.describe(question="Optional question to cast on.")
    async def iching(self, interaction: discord.Interaction, question: str | None = None) -> None:
        await interaction.response.defer(thinking=True)
        cast = divination.cast_iching()
        changing = (f"changing lines: {cast.changing_lines}" if cast.changing_lines else "no changing lines")
        facts = (f"I Ching cast{f' on: {question}' if question else ''}:\n"
                 f"Hexagram {cast.number} — {cast.name} ({changing}).\n"
                 "Read the hexagram and any movement from the changing lines.")
        await self._read(interaction, f"☯ I Ching — {cast.name}", facts, discord.Color.greyple())

    @app_commands.command(name="dream", description="Describe a dream; get a symbolic interpretation.")
    @app_commands.describe(dream="What happened in the dream.")
    async def dream(self, interaction: discord.Interaction, dream: str) -> None:
        await interaction.response.defer(thinking=True)
        facts = f"Interpret this dream symbolically:\n\"{dream.strip()}\""
        await self._read(interaction, "🌙 Dream Reading", facts, discord.Color.dark_blue())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DivinationCog(bot))
