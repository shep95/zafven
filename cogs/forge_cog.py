"""/forge — describe a feature; zafven plans it (narrative), then forges code on approval.

The build-side sibling of /audit. Honors the Narrative Forge approval gate: it
produces the plan first and only writes code after the requester clicks approve.
"""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.forge")

PLAN_MAX_TOKENS = 1400
CODE_MAX_TOKENS = 8000


def _system() -> str:
    return f"{load_brain('persona')}\n\n--- CODE FORGE PROTOCOL ---\n{load_brain('code_forge')}"


def _file(text: str, name: str) -> discord.File:
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=name)


class BuildView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int, system: str, spec: str, plan: str) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.author_id = author_id
        self.system = system
        self.spec = spec
        self.plan = plan

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the requester can forge this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Forge the code", style=discord.ButtonStyle.success)
    async def forge(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.disabled = True
        await interaction.response.edit_message(view=self)
        prompt = (
            "The user APPROVES this plan. Forge the COMPLETE, production-grade, typed code that "
            "implements it (no fragments), with a short changelog. Validate inputs, no hardcoded "
            f"secrets.\n\n=== SPEC ===\n{self.spec}\n\n=== APPROVED PLAN ===\n{self.plan}"
        )
        try:
            code = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                self.system, prompt, web_search=False, max_tokens=CODE_MAX_TOKENS)
        except GatewayError as exc:
            log.warning("forge code failed: %s", exc)
            await interaction.followup.send("🔌 Forge engine unreachable. Try again shortly.", ephemeral=True)
            return
        await interaction.followup.send(content="🛠️ **Forged code** attached.",
                                        file=_file(code, "zafven_forged.md"))


class ForgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="forge", description="Describe a feature; zafven plans it, then writes the code on approval.")
    @app_commands.describe(spec="What you want built.", language="Target language/stack (optional).")
    async def forge(self, interaction: discord.Interaction, spec: str, language: str | None = None) -> None:
        if len(spec.strip()) < 10:
            await interaction.response.send_message("❌ Give a fuller spec.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        lang = f" Target stack: {language}." if language else ""
        prompt = (
            f"Plan this build.{lang} Translate the intent into a clear design narrative: the "
            "approach, the modules, key decisions, edge cases, and risks. Do NOT write code yet — "
            f"wait for approval.\n\n=== SPEC ===\n{spec.strip()}"
        )
        system = _system()
        try:
            plan = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, prompt, web_search=False, max_tokens=PLAN_MAX_TOKENS)
        except GatewayError as exc:
            log.warning("forge plan failed: %s", exc)
            await interaction.followup.send("🔌 Forge engine unreachable. Try again shortly.")
            return

        embed = discord.Embed(
            title="🏗️ Build Plan",
            description=plan[:4000] + ("…\n\n*(full plan attached)*" if len(plan) > 4000 else ""),
            color=discord.Color.orange())
        embed.set_footer(text="Approve below to forge the code")
        view = BuildView(self.bot, interaction.user.id, system, spec.strip(), plan)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ForgeCog(bot))
