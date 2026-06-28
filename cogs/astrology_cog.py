"""/vedic — Vedic astrology reading: deterministic chart + Gemini narration."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import vedic, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.vedic")


class AstrologyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="vedic", description="A Vedic (sidereal) astrology reading.")
    @app_commands.describe(
        birth_date="Your birth date, e.g. 1995-08-23",
        birth_time="Optional birth time for a precise chart, e.g. 14:30 or 2:30pm",
        latitude="Optional birth latitude (decimal), e.g. 28.61",
        longitude="Optional birth longitude (decimal), e.g. 77.21",
    )
    async def vedic(self, interaction: discord.Interaction, birth_date: str,
                    birth_time: str | None = None, latitude: float | None = None,
                    longitude: float | None = None) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        chart = vedic.compute_chart(bdate, birth_time, latitude, longitude)

        facts = (
            f"Moon sign (rashi): {chart.moon_sign} — {chart.moon_sign_traits}\n"
            f"Nakshatra: {chart.nakshatra} (ruled by {chart.nakshatra_planet}) — {chart.nakshatra_keyword}\n"
            f"Ascendant: {chart.ascendant or 'not computed (no birth time/place given)'}"
            + (f" — {chart.ascendant_traits}" if chart.ascendant_traits else "")
            + f"\nPrecision: {'full chart' if chart.precise else 'date-only approximation'}"
        )
        user_prompt = (
            f"Write a Vedic reading for {interaction.user.display_name}. "
            f"Use ONLY these computed values:\n{facts}\n"
            "Lead with the Moon sign, then the nakshatra, then the ascendant if present. "
            "4-6 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("vedic"), user_prompt, web_search=False)
        except GatewayError as exc:
            log.warning("vedic narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🔭 Vedic Reading — {interaction.user.display_name}",
            description=reading[:4000],
            color=discord.Color.dark_purple(),
        )
        embed.set_footer(text="zafven • for reflection & entertainment, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AstrologyCog(bot))
