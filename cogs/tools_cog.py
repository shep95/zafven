"""/research, /tldr, /askdoc — Gemini-powered knowledge tools."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.tools")

MAX_PDF_BYTES = 15 * 1024 * 1024


def _persona(extra: str) -> str:
    return f"{load_brain('persona')}\n\n--- TASK MODE ---\n{extra}"


class ToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="research", description="Deep-dive a topic with live web research + citations.")
    @app_commands.describe(topic="What to research.")
    async def research(self, interaction: discord.Interaction, topic: str) -> None:
        await interaction.response.defer(thinking=True)
        system = _persona(
            "You are a research analyst. Use web search to gather current, accurate facts. "
            "Give a structured briefing with concrete details and cite sources inline. "
            "If you're unsure, say so. No esoteric flourish here — be clear and factual.")
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, f"Research this and brief me: {topic}", web_search=True, max_tokens=1600)
        except GatewayError as exc:
            log.warning("research failed: %s", exc)
            await interaction.followup.send("🔌 Research engine unreachable. Try again shortly.")
            return
        embed = discord.Embed(title=f"📚 Research — {topic[:200]}", description=out[:4000],
                              color=discord.Color.blue())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="tldr", description="Summarize recent messages in this channel.")
    @app_commands.describe(count="How many recent messages to summarize (10-200). Default 50.")
    async def tldr(self, interaction: discord.Interaction, count: int = 50) -> None:
        await interaction.response.defer(thinking=True)
        count = max(10, min(count, 200))
        if not interaction.channel.permissions_for(interaction.guild.me).read_message_history:
            await interaction.followup.send("❌ I can't read this channel's history.")
            return
        lines = []
        async for msg in interaction.channel.history(limit=count):
            if msg.content.strip():
                lines.append(f"{msg.author.display_name}: {msg.content}")
        lines.reverse()
        if len(lines) < 3:
            await interaction.followup.send("Not enough recent text to summarize.")
            return
        transcript = "\n".join(lines)[:60000]
        system = _persona("You summarize a chat log. Give a tight bullet recap of what was "
                          "discussed and any decisions/open questions. Neutral, no profiling of people.")
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, f"Summarize this conversation:\n\n{transcript}", web_search=False, max_tokens=900)
        except GatewayError as exc:
            log.warning("tldr failed: %s", exc)
            await interaction.followup.send("🔌 Summarizer unreachable. Try again shortly.")
            return
        embed = discord.Embed(title=f"📝 TL;DR — last {len(lines)} messages", description=out[:4000],
                              color=discord.Color.teal())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="askdoc", description="Upload a PDF and ask a question about it.")
    @app_commands.describe(document="A PDF file.", question="What you want to know.")
    async def askdoc(self, interaction: discord.Interaction, document: discord.Attachment,
                     question: str) -> None:
        if document.size > MAX_PDF_BYTES or (document.content_type or "") not in (
                "application/pdf", "text/plain"):
            await interaction.response.send_message("❌ Attach a PDF (or .txt) under 15 MB.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        data = await document.read()
        system = _persona("You answer questions about the attached document. Ground every answer in "
                          "the document; if it isn't covered, say so. Quote sparingly.")
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, f"Question about the attached document: {question}",
                image_bytes=data, image_mime=document.content_type, web_search=False, max_tokens=1400)
        except GatewayError as exc:
            log.warning("askdoc failed: %s", exc)
            await interaction.followup.send("🔌 Document oracle unreachable. Try again shortly.")
            return
        embed = discord.Embed(title=f"📄 {document.filename}", description=out[:4000],
                              color=discord.Color.dark_teal())
        embed.add_field(name="You asked", value=question[:1024], inline=False)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ToolsCog(bot))
