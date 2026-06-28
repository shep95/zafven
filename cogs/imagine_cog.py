"""/imagine — upload an image; zafven describes and interprets it (Gemini vision).

Describe + symbolic interpretation only. The imagine brain forbids identifying
real people or locating where a photo was taken (that would be surveillance).
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.imagine")

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _system_prompt() -> str:
    return f"{load_brain('persona')}\n\n--- IMAGINE PROTOCOL ---\n{load_brain('imagine')}"


class ImagineCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="imagine",
                          description="Upload an image; zafven describes and interprets it.")
    @app_commands.describe(image="The image to read.",
                           question="Optional: what to focus on (e.g. 'what's the symbolism?').")
    async def imagine(self, interaction: discord.Interaction, image: discord.Attachment,
                      question: str | None = None) -> None:
        if image.size > MAX_IMAGE_BYTES or not (image.content_type or "").startswith("image/"):
            await interaction.response.send_message("❌ Attach an image under 8 MB.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        data = await image.read()
        user_prompt = (
            (question.strip() if question else "Describe this image, then interpret its mood and symbolism.")
            + "\n(Describe and interpret only — do not identify real people or where it was taken.)"
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                _system_prompt(), user_prompt,
                image_bytes=data, image_mime=image.content_type, web_search=False)
        except GatewayError as exc:
            log.warning("imagine failed: %s", exc)
            await interaction.followup.send("🔌 The vision engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title="🖼️ zafven sees…",
            description=reading[:4000],
            color=discord.Color.dark_teal(),
        )
        embed.set_thumbnail(url=image.url)
        embed.set_footer(text="zafven • image description & interpretation, for reflection")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImagineCog(bot))
