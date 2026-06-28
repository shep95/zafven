"""/numerology — numbers computed in code, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import numerology, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.numerology")


class NumerologyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="numerology", description="A numerology reading from your name and birth date.")
    @app_commands.describe(full_name="Your full birth name", birth_date="e.g. 1995-08-23")
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
        facts = "\n".join([
            f"Life Path: {r.life_path} ({numerology.title(r.life_path)})",
            f"Expression: {r.expression} ({numerology.title(r.expression)})",
            f"Soul Urge: {r.soul_urge} ({numerology.title(r.soul_urge)})",
            f"Personality: {r.personality} ({numerology.title(r.personality)})",
            f"Birthday: {r.birthday} ({numerology.title(r.birthday)})",
        ])
        user_prompt = (
            f"Write a numerology reading for {r.name} (born {r.birth.isoformat()}). "
            f"Use ONLY these computed numbers:\n{facts}\n"
            "Open with the Life Path, weave the rest into a coherent portrait. 4-6 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("numerology"), user_prompt, web_search=False)
        except GatewayError as exc:
            log.warning("numerology narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🔢 Numerology — {r.name}",
            description=reading[:4000],
            color=discord.Color.gold(),
        )
        embed.set_footer(text="zafven • for reflection & entertainment, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NumerologyCog(bot))
