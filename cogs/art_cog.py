"""/sigil and /portrait — procedurally generated art (Pillow, deterministic)."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import art, numerology, lunar, dates

log = logging.getLogger("zafven.art")


def _file(data: bytes, name: str) -> discord.File:
    return discord.File(io.BytesIO(data), filename=name)


class ArtCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="sigil", description="Forge a personal sigil from an intent.")
    @app_commands.describe(intent="Your intent, e.g. 'focus and discipline'.")
    async def sigil(self, interaction: discord.Interaction, intent: str) -> None:
        if len(intent.strip()) < 3:
            await interaction.response.send_message("❌ Give a fuller intent.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        png = art.sigil(intent.strip())
        embed = discord.Embed(
            title="🜲 Your Sigil", description=f"Forged from: *{intent.strip()}*",
            color=discord.Color.purple())
        embed.set_image(url="attachment://sigil.png")
        embed.set_footer(text="zafven • charge it however you like")
        await interaction.followup.send(embed=embed, file=_file(png, "sigil.png"))

    @app_commands.command(name="portrait", description="A frequency portrait from your numerology.")
    @app_commands.describe(full_name="Your full name", birth_date="e.g. 2005-09-26")
    async def portrait(self, interaction: discord.Interaction, full_name: str, birth_date: str) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        r = numerology.build_report(full_name, bdate)
        nums = [r.day, r.life_path, r.expression, r.soul_urge, r.personality]
        try:
            nums.append(numerology.lunar_numbers(*self._lunar(bdate)).driver)
        except Exception:  # noqa: BLE001
            pass
        png = art.frequency_portrait(full_name, nums)
        embed = discord.Embed(
            title=f"🌀 Frequency Portrait — {r.name}",
            description=f"Driver {r.day} · Life Path {r.life_path} · Expression {r.expression}",
            color=discord.Color.magenta())
        embed.set_image(url="attachment://portrait.png")
        embed.set_footer(text="zafven • procedural art from your numbers")
        await interaction.followup.send(embed=embed, file=_file(png, "portrait.png"))

    @staticmethod
    def _lunar(bdate):
        info = lunar.to_lunar(bdate)
        return info.lunar_month, info.lunar_day


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArtCog(bot))
