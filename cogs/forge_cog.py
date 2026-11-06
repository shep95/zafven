"""/forge — describe a feature and receive its design and generated code."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.forge")

CODE_MAX_TOKENS = 8000


def _system() -> str:
    return (f"{load_brain('persona')}\n\n--- DELIBERATE REASONING ---\n{load_brain('deliberate')}"
            f"\n\n--- CODE FORGE PROTOCOL ---\n{load_brain('code_forge')}")


def _file(text: str, name: str) -> discord.File:
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=name)


class ForgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="forge", description="Describe a feature; receive a design and generated code.")
    @app_commands.describe(spec="What you want built.", language="Target language/stack (optional).")
    async def forge(self, interaction: discord.Interaction, spec: str, language: str | None = None) -> None:
        if len(spec.strip()) < 10:
            await interaction.response.send_message("❌ Give a fuller spec.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        lang = f" Target stack: {language}." if language else ""
        prompt = (
            f"Plan this build.{lang} Translate the intent into a clear design narrative: the "
            "approach, modules, decisions and edge cases. Then generate the complete code "
            "and a short changelog. Do not claim it was executed or tested. "
            f"\n\n=== SPEC ===\n{spec.strip()}"
        )
        system = _system()
        try:
            result = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, prompt, web_search=False, max_tokens=CODE_MAX_TOKENS)
        except GatewayError as exc:
            log.warning("forge generation failed: %s", exc)
            await interaction.followup.send("🔌 Forge engine unreachable. Try again shortly.")
            return

        await interaction.followup.send(
            content="🛠️ Design and generated code attached. Code has not been executed.",
            file=_file(result, "zafven_forged.md"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ForgeCog(bot))
