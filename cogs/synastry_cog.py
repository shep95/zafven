"""/synastry — compatibility between two people (numerology + Chinese zodiac), narrated."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import synastry, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.synastry")


class SynastryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="synastry", description="Compatibility reading between two people.")
    @app_commands.describe(
        name_a="First person's name", date_a="First person's birth date, e.g. 2005-09-26",
        name_b="Second person's name", date_b="Second person's birth date")
    async def synastry(self, interaction: discord.Interaction, name_a: str, date_a: str,
                       name_b: str, date_b: str) -> None:
        try:
            da = dates.parse_date(date_a)
            db = dates.parse_date(date_b)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        m = synastry.compute(name_a.strip(), da, name_b.strip(), db)
        facts = (
            f"Compatibility ({m.score}/100 — {m.headline}):\n"
            f"{m.name_a}: Life Path {m.life_path_a}, {m.animal_a}\n"
            f"{m.name_b}: Life Path {m.life_path_b}, {m.animal_b}\n"
            "Read the dynamic between them — strengths, friction, and how to harmonise. "
            "3-4 short paragraphs."
        )
        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("numerology"), facts, web_search=False, max_tokens=900)
        except GatewayError as exc:
            log.warning("synastry failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"💞 Synastry — {m.name_a} × {m.name_b}",
            description=reading[:4000], color=discord.Color.pink())
        embed.add_field(name="Score", value=f"{m.score}/100 — {m.headline}")
        embed.add_field(name="Animals", value=f"{m.animal_a} × {m.animal_b}")
        embed.set_footer(text="zafven • for fun, not fate")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SynastryCog(bot))
