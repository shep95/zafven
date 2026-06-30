"""/synthesize — cross-domain research & logic.

Strips a question to its underlying structure, pulls governing principles from
several distant fields (web-grounded), bridges them, and produces a conclusion no
single domain would reach alone. The thinking style the smartest people use.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import textsplit
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.synthesize")


class SynthesizeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="synthesize",
        description="Cross-domain research: connect multiple fields to crack a question.")
    @app_commands.describe(
        question="The question or problem to think across domains about.",
        domains="Optional: comma-separated fields to bridge (else she picks the best ones).")
    async def synthesize(self, interaction: discord.Interaction, question: str,
                         domains: str = "") -> None:
        await interaction.response.defer(thinking=True)
        ask = f"QUESTION: {question}"
        if domains.strip():
            ask += f"\nDeliberately bridge these domains: {domains.strip()}"
        ask += ("\n\nUse web research to ground each domain's principle in what's actually known. "
                "Then run the full synthesis method and give the cross-domain conclusion.")
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                load_brain("cross_domain"), ask, web_search=True, max_tokens=1900)
        except GatewayError as exc:
            log.warning("synthesize failed: %s", exc)
            await interaction.followup.send("🔌 Synthesis engine unreachable. Try again shortly.")
            return

        header = discord.Embed(
            title="🧬 Cross-domain synthesis",
            description=f"**{question[:240]}**", color=discord.Color.blurple())
        header.set_footer(text="Structural reasoning across fields • analogies are hypotheses, not proof")
        await interaction.followup.send(embed=header)
        for part in textsplit.chunk(out):
            await interaction.followup.send(part)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SynthesizeCog(bot))
