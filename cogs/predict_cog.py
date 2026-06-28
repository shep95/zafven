"""/predict — entertainment astrological outlook.

Uses Gemini's Google Search grounding to anchor itself in *current* planetary
transits, and optionally Gemini vision to read an uploaded birth-chart image. The
persona + anti-spiral guards keep this firmly in entertainment territory: no
financial, medical, or real-world-event forecasting, no dated guarantees.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import vedic, dates, premium
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.predict")

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class PredictCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="predict", description="A for-fun astrological outlook based on current transits.")
    @app_commands.describe(
        birth_date="Your birth date, e.g. 1995-08-23",
        focus="What to focus the outlook on (e.g. general, creativity, relationships).",
        chart_image="Optional: upload a birth-chart image for zafven to read.",
    )
    @premium.premium_only()
    async def predict(self, interaction: discord.Interaction, birth_date: str,
                      focus: str = "general", chart_image: discord.Attachment | None = None) -> None:
        try:
            bdate = dates.parse_date(birth_date)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        chart = vedic.compute_chart(bdate)

        image_bytes = image_mime = None
        if chart_image is not None:
            if chart_image.size > MAX_IMAGE_BYTES or not (chart_image.content_type or "").startswith("image/"):
                await interaction.followup.send("❌ Please attach an image under 5 MB.")
                return
            image_bytes = await chart_image.read()
            image_mime = chart_image.content_type

        user_prompt = (
            f"Give {interaction.user.display_name} a forward-looking astrological *outlook* "
            f"(focus: {focus}). Their natal Moon sign is {chart.moon_sign} and nakshatra is "
            f"{chart.nakshatra}. Use web search to ground it in the CURRENT major planetary "
            "transits this week. Frame everything as energetic tendencies and self-reflection "
            "prompts — NOT as predictions of real events, money, health, or fixed dates. "
            "4-6 short paragraphs."
        )
        if image_bytes:
            user_prompt += " The attached image is the reader's chart — describe what you can see and weave it in."

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("vedic"), user_prompt,
                image_bytes=image_bytes, image_mime=image_mime, web_search=True)
        except GatewayError as exc:
            log.warning("predict narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🌌 Outlook — {interaction.user.display_name} ({focus})",
            description=reading[:4000],
            color=discord.Color.blue(),
        )
        embed.set_footer(text="zafven • symbolic outlook for reflection — not a forecast, not advice")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PredictCog(bot))
