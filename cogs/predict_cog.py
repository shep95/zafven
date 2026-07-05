"""`/predict — ask a free-form question; zafven researches it + reads it astrologically.

Uses Gemini Google-Search grounding for current real context, then an astrological
lens. No content restrictions.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.predict")


class PredictCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="predict", description="Ask the oracle a question — it researches it + reads it astrologically.")
    @app_commands.describe(
        question="Your question, e.g. 'what's the vibe for BTC this week?'",
        birth_date="Optional: your birth date, to weave your chart into the answer.",
    )
    async def predict(self, interaction: discord.Interaction, question: str,
                      birth_date: str | None = None) -> None:
        if len(question.strip()) < 4:
            await interaction.response.send_message("❌ Ask a fuller question.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        context = f"The asker's birth date is {birth_date}." if birth_date else ""
        user_prompt = (
            f"Question from {interaction.user.display_name}: \"{question.strip()}\"\n{context}\n"
            "Use web search for the CURRENT real situation around this, then give the oracle "
            "reading per your rules. Answer directly — no hedging, no disclaimers. 4-6 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("prediction"), user_prompt, web_search=True, max_tokens=1400)
        except GatewayError as exc:
            log.warning("predict failed: %s", exc)
            await interaction.followup.send("🔌 The oracle is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title="🔮 The Oracle",
            description=reading[:4000],
            color=discord.Color.blue(),
        )
        embed.add_field(name="You asked", value=question[:1024], inline=False)
        embed.set_footer(text="zafven • the oracle")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PredictCog(bot))
