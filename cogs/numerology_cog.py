"""/numerology — full solar + lunar reading, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import numerology, lunar, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.numerology")


class NumerologyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="numerology", description="Full numerology — solar + Chinese-lunar birthday, every number.")
    @app_commands.describe(full_name="Your full birth name", birth_date="Gregorian, e.g. 2005-09-26")
    async def numerology(self, interaction: discord.Interaction, full_name: str, birth_date: str) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if not any(c.isalpha() for c in full_name):
            await interaction.response.send_message("❌ Provide a name with letters.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        r = numerology.build_report(full_name, bdate)

        def line(label: str, n: int) -> str:
            return f"{label}: {n} — {numerology.title(n)} (ruler: {numerology.planet(n)})"

        solar = "\n".join([
            line("Driver / Day (core self)", r.day),
            line("Conductor / Life Path (journey)", r.life_path),
            line("Month", r.month),
            line("Year", r.year),
            line("Expression / Destiny (talents)", r.expression),
            line("Soul Urge (craving)", r.soul_urge),
            line("Personality (mask)", r.personality),
            line("Maturity (later life)", r.maturity),
        ])

        lunar_block = ""
        try:
            info = lunar.to_lunar(bdate)
            ln = numerology.lunar_numbers(info.lunar_month, info.lunar_day)
            lunar_block = (
                f"\n\nLUNAR ENGINE (Chinese lunar birthday: month {ln.lunar_month}, day {ln.lunar_day}):\n"
                + line("Lunar Driver (hidden self)", ln.driver) + "\n"
                + line("Lunar Month", ln.month_number)
            )
        except Exception as exc:  # noqa: BLE001
            log.info("lunar numbers skipped: %s", exc)

        user_prompt = (
            f"Write a full numerology reading for {r.name} (born {r.birth.isoformat()}). "
            f"Use ONLY these computed numbers. Read EVERY one, with its planet ruler, and "
            f"explain how the Driver and Conductor interact:\n\nSOLAR ENGINE:\n{solar}{lunar_block}\n\n"
            "6-9 short paragraphs. Do not stop at Life Path."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("numerology"), user_prompt, web_search=False, max_tokens=1600)
        except GatewayError as exc:
            log.warning("numerology narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🔢 Numerology — {r.name}",
            description=reading[:4000],
            color=discord.Color.gold(),
        )
        embed.add_field(name="Driver / Conductor", value=f"{r.day} / {r.life_path}")
        embed.set_footer(text="Pythagorean + Vedic numerology • for entertainment")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NumerologyCog(bot))
