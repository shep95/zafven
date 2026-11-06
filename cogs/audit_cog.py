"""/audit — review uploaded code and return proposed fixes without a second approval."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import code_intake
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.audit")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
AUDIT_MAX_TOKENS = 8000


def _system_prompt() -> str:
    return (f"{load_brain('persona')}\n\n--- DELIBERATE REASONING ---\n{load_brain('deliberate')}"
            f"\n\n--- CODE FORGE PROTOCOL ---\n{load_brain('code_forge')}")


def _as_file(text: str, name: str) -> discord.File:
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=name)


class AuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="audit",
                          description="Upload code or a .zip for a narrative security + quality audit.")
    @app_commands.describe(file="A source file or a .zip of your project.")
    async def audit(self, interaction: discord.Interaction, file: discord.Attachment) -> None:
        if file.size > MAX_UPLOAD_BYTES:
            await interaction.response.send_message("❌ Upload must be under 10 MB.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        data = await file.read()
        intake = code_intake.from_attachment(file.filename, data)
        if not intake.files:
            await interaction.followup.send(
                "❌ I couldn't find readable source files in that upload "
                "(text-based code files or a .zip of them).")
            return

        blob = code_intake.build_blob(intake)
        system = _system_prompt()
        user_prompt = (
            "Audit this codebase. Run the pipeline: TRANSLATE → COMPREHEND → AUDIT (logic, "
            "workflow, bug, security, software-supply-chain) → REBUILD the corrected narrative. "
            "Include proposed corrected files and a changelog after the findings. "
            "Do not claim to have run or tested the code.\n\n"
            f"=== CODE ({len(intake.files)} file(s)) ===\n{blob}"
        )
        try:
            audit_text = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, user_prompt, web_search=False, max_tokens=AUDIT_MAX_TOKENS)
        except GatewayError as exc:
            log.warning("audit failed: %s", exc)
            await interaction.followup.send("🔌 The audit engine is unreachable right now. Try again shortly.")
            return

        note = (f"📂 {len(intake.files)} file(s) audited"
                + (f" · {intake.skipped} skipped" if intake.skipped else "")
                + (" · input truncated" if intake.truncated else ""))
        embed = discord.Embed(
            title=f"🔎 Code Audit — {file.filename}",
            description=audit_text[:1500] + ("…\n\n*(full report attached)*" if len(audit_text) > 1500 else ""),
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"{note} • proposed changes; code has not been executed")

        await interaction.followup.send(embed=embed, file=_as_file(audit_text, "zafven_audit.md"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))
