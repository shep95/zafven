"""/help — lists zafven's commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="What can zafven do?")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🜲 zafven — commands", color=discord.Color.dark_purple())
        embed.add_field(
            name="🔮 Readings (LLM-narrated, entertainment)",
            value=("`/vedic <birth_date> [time] [lat] [lon]` — Vedic astrology\n"
                   "`/numerology <full_name> <birth_date>` — numerology\n"
                   "`/zodiac <birth_date>` — Chinese zodiac\n"
                   "`/predict <birth_date> [focus] [chart_image]` — astrological outlook (web + vision)\n"
                   "`/vibe [share]` — a playful read of *your own* chat style"),
            inline=False)
        embed.add_field(
            name="🔎 Code audit (premium)",
            value=("`/audit <file>` — upload code or a .zip; zafven narrates it, finds logic / "
                   "workflow / bug / security / supply-chain flaws with app impact, then forges "
                   "the fixed code on your approval"),
            inline=False)
        embed.add_field(
            name="🛡️ Server management",
            value=("`/kick_inactive [days] [dry_run] [message]` — preview/remove inactive members "
                   "with a reinvite DM (dry-run by default)\n"
                   "Join/leave events are logged automatically."),
            inline=False)
        embed.set_footer(text="Readings are for reflection & entertainment, not advice.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
