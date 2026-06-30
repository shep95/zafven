"""/council — superposition & collapse: answer a hard question by elimination.

Generates several diverse candidate answers, then runs an adversarial oracle that
stress-tests them against your constraints, kills the weak, and ships the single
survivor. Slower than a normal answer (it runs a real best-of-N internally) — use
it when being *right* matters more than being fast.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import textsplit
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.council")


class CouncilCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="council",
        description="Hard question? She spawns competing answers, kills the weak, ships the survivor.")
    @app_commands.describe(
        question="The hard question or problem.",
        constraints="Optional: the hard requirements the answer must satisfy.")
    async def council(self, interaction: discord.Interaction, question: str,
                      constraints: str = "") -> None:
        await interaction.response.defer(thinking=True)
        try:
            answer = await self.bot.gateway.council(  # type: ignore[attr-defined]
                load_brain("superposition"), question, constraints=constraints,
                candidates=3, web_search=False, max_tokens=1500)
        except GatewayError as exc:
            log.warning("council failed: %s", exc)
            await interaction.followup.send("🔌 The council couldn't reach a verdict. Try again shortly.")
            return

        header = discord.Embed(
            title="⚛️ Collapsed to one answer",
            description=f"**{question[:240]}**", color=discord.Color.dark_teal())
        header.set_footer(text="3 candidates competed • adversarially pruned • survivor shipped")
        await interaction.followup.send(embed=header)
        for part in textsplit.chunk(answer):
            await interaction.followup.send(part)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CouncilCog(bot))
