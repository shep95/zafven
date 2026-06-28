"""/zodiac — Chinese zodiac: year + month + day pillars from the lunar date, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import lunar, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.zodiac")


class ZodiacCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="zodiac", description="Chinese zodiac reading — year, month & day animals from your lunar birthday.")
    @app_commands.describe(birth_date="Your Gregorian birth date, e.g. 2005-09-26")
    async def zodiac(self, interaction: discord.Interaction, birth_date: str) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            info = lunar.to_lunar(bdate)
        except Exception as exc:  # noqa: BLE001 — out-of-range dates etc.
            log.warning("lunar conversion failed: %s", exc)
            await interaction.followup.send("❌ I can only convert dates between 1900 and 2099.")
            return

        leap = " (leap month)" if info.leap_month else ""
        facts = (
            f"Gregorian: {info.greg.isoformat()}\n"
            f"Chinese lunar birthday: month {info.lunar_month}, day {info.lunar_day}{leap}\n"
            f"YEAR pillar (outer self): {info.element} {info.year_animal} — {info.year_animal_traits}\n"
            f"MONTH pillar (inner self): {info.month_animal}\n"
            f"DAY pillar (secret self): {info.day_animal}"
        )
        user_prompt = (
            f"Write a Chinese zodiac reading for {interaction.user.display_name}. "
            f"Use ONLY these computed values:\n{facts}\n"
            "Read all three pillars and the tension between them. 3-5 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("zodiac"), user_prompt, web_search=False)
        except GatewayError as exc:
            log.warning("zodiac narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🐉 Chinese Zodiac — {info.element} {info.year_animal}",
            description=reading[:4000],
            color=discord.Color.red(),
        )
        embed.add_field(name="Lunar birthday", value=f"Month {info.lunar_month}, Day {info.lunar_day}{leap}")
        embed.add_field(name="Inner / Secret", value=f"{info.month_animal} / {info.day_animal}")
        embed.set_footer(text="zafven • for reflection & entertainment, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ZodiacCog(bot))
