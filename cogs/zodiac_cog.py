"""/zodiac — Chinese zodiac animal + element, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import zodiac, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.zodiac")


class ZodiacCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="zodiac", description="Your Chinese zodiac animal + element reading.")
    @app_commands.describe(birth_date="e.g. 1995-08-23")
    async def zodiac(self, interaction: discord.Interaction, birth_date: str) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        sign = zodiac.compute_sign(bdate)
        facts = (f"Element + Animal: {sign.element} {sign.animal} ({sign.animal_traits})\n"
                 f"Chinese year used: {sign.year} (Feb-4 boundary approximation)")
        user_prompt = (
            f"Write a Chinese zodiac reading for {interaction.user.display_name}. "
            f"Use ONLY these computed values:\n{facts}\n"
            "Blend the element with the animal into a vivid archetype. 3-4 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("zodiac"), user_prompt, web_search=False)
        except GatewayError as exc:
            log.warning("zodiac narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🐉 Chinese Zodiac — {sign.element} {sign.animal}",
            description=reading[:4000],
            color=discord.Color.red(),
        )
        embed.set_footer(text="zafven • for reflection & entertainment, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ZodiacCog(bot))
