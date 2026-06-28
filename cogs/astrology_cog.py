"""/vedic — a real Vedic chart from date + time + place, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import vedic, dates, geocode
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.vedic")


class AstrologyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="vedic", description="A real Vedic reading — needs birth date, time, and place.")
    @app_commands.describe(
        birth_date="Your birth date, e.g. 2005-09-26",
        birth_time="Your exact birth time, e.g. 14:30 or 2:30pm",
        birth_place="Your birth city/town, e.g. 'Columbus, Ohio'",
    )
    async def vedic(self, interaction: discord.Interaction, birth_date: str,
                    birth_time: str, birth_place: str) -> None:
        try:
            bdate = dates.parse_date(birth_date)
            hour, minute = vedic.parse_time(birth_time)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        place = await geocode.lookup(birth_place)
        if place is None:
            await interaction.followup.send(
                f"❌ I couldn't find **{birth_place}**. Try a more specific city, e.g. `Columbus, Ohio, USA`.")
            return

        chart = vedic.compute_precise(bdate, hour, minute, place.lat, place.lon, place.tz_name)

        facts = [
            f"Birthplace: {place.display} (lat {place.lat:.2f}, lon {place.lon:.2f}, tz {place.tz_name or 'estimated'})",
            f"Ascendant (Lagna): {chart.ascendant or 'n/a'}"
            + (f" — {chart.ascendant_traits}" if chart.ascendant_traits else ""),
            f"Moon sign (Rashi): {chart.moon_sign} — {chart.moon_sign_traits}",
            f"Nakshatra: {chart.nakshatra} pada {chart.pada} (ruled by {chart.nakshatra_planet})",
            f"Sun sign: {chart.sun_sign or 'n/a'}",
        ]
        if chart.mahadasha:
            facts.append(f"Current Mahādashā: {chart.mahadasha} (until {chart.maha_end}), "
                         f"Antardashā: {chart.antardasha}")
        if not chart.precise:
            facts.append("NOTE: ephemeris unavailable — this is a date-only approximation.")

        user_prompt = (
            f"Write a deep Vedic reading for {interaction.user.display_name}. Use ONLY these "
            f"computed values:\n" + "\n".join(facts) + "\n\n"
            "Lead with the Ascendant (the mask), then the Moon sign + nakshatra/pada (the inner "
            "world), then the Sun, then read the current Mahādashā/Antardashā as the season of life. "
            "5-7 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("vedic"), user_prompt, web_search=False, max_tokens=1600)
        except GatewayError as exc:
            log.warning("vedic narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🔭 Vedic Reading — {interaction.user.display_name}",
            description=reading[:4000], color=discord.Color.dark_purple())
        if chart.ascendant:
            embed.add_field(name="Lagna / Moon", value=f"{chart.ascendant} / {chart.moon_sign}")
        if chart.mahadasha:
            embed.add_field(name="Dashā", value=f"{chart.mahadasha} → {chart.antardasha}")
        embed.set_footer(text="Swiss Ephemeris (Lahiri) • for reflection & entertainment, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AstrologyCog(bot))
