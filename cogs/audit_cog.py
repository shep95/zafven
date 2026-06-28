"""/audit — upload code or a .zip; zafven runs the narrative code-forge audit.

Pipeline (from brains/code_forge.md): translate code to a story, comprehend it,
audit it across logic / workflow / bug / security / supply-chain lenses, then
rebuild a corrected narrative. The FIXED CODE is only produced after the user
clicks approve — honoring the Narrative Forge hard approval gate.
"""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import code_intake, premium
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.audit")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
AUDIT_MAX_TOKENS = 6000
FORGE_MAX_TOKENS = 8000


def _system_prompt() -> str:
    return f"{load_brain('persona')}\n\n--- CODE FORGE PROTOCOL ---\n{load_brain('code_forge')}"


def _as_file(text: str, name: str) -> discord.File:
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=name)


class ForgeView(discord.ui.View):
    """Offers the approval gate: forge the fixed code on request."""

    def __init__(self, bot: commands.Bot, author_id: int, system_prompt: str,
                 code_blob: str, audit_text: str) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.author_id = author_id
        self.system_prompt = system_prompt
        self.code_blob = code_blob
        self.audit_text = audit_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the uploader can forge the fix.", ephemeral=True)
            return False
        if not premium.has_access(interaction):
            text, view = premium.build_upsell(interaction)
            await interaction.response.send_message(text, view=view, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Forge the fixed code", style=discord.ButtonStyle.success)
    async def forge(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.disabled = True
        await interaction.response.edit_message(view=self)
        followup = interaction.followup

        prompt = (
            "The user APPROVES the corrected narrative below. Now FORGE the fixed code.\n"
            "Output the COMPLETE corrected file(s) — no fragments — production-grade and typed, "
            "with a short changelog mapping each change back to a finding.\n\n"
            f"=== APPROVED AUDIT ===\n{self.audit_text}\n\n=== ORIGINAL CODE ===\n{self.code_blob}"
        )
        try:
            fixed = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                self.system_prompt, prompt, web_search=False, max_tokens=FORGE_MAX_TOKENS)
        except GatewayError as exc:
            log.warning("forge failed: %s", exc)
            await followup.send("🔌 The forge engine is unreachable right now. Try again shortly.", ephemeral=True)
            return

        await followup.send(content="🛠️ **Forged fix** — complete corrected code attached.",
                            file=_as_file(fixed, "zafven_fixed_code.md"))


class AuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="audit",
                          description="Upload code or a .zip for a narrative security + quality audit.")
    @app_commands.describe(file="A source file or a .zip of your project.")
    @premium.premium_only()
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
            "Follow the output contract. Do NOT write the fixed code yet — that waits for approval.\n\n"
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
        embed.set_footer(text=f"{note} • click below to forge the fixed code")

        view = ForgeView(self.bot, interaction.user.id, system, blob, audit_text)
        await interaction.followup.send(embed=embed, file=_as_file(audit_text, "zafven_audit.md"), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))
