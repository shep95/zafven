"""Quote-image cards from custom text, actual messages, or image-inspired writing."""
from __future__ import annotations

import asyncio
import io
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.brain_loader import load
from core.model_gateway import GatewayError
from core.quote_images import MAX_IMAGE_BYTES, MAX_QUOTE_CHARS, QuoteImageError, render_quote, vision_image

log = logging.getLogger("zafven.quote")
MESSAGE_LINK = re.compile(r"^https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?$")


class QuoteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.menu = app_commands.ContextMenu(name="Quote this message", callback=self.quote_message)
        bot.tree.add_command(self.menu)

    def cog_unload(self):
        self.bot.tree.remove_command(self.menu.name, type=discord.AppCommandType.message)

    async def source_message(self, interaction, link):
        match = MESSAGE_LINK.fullmatch(link.strip())
        if match is None or interaction.guild is None or int(match[1]) != interaction.guild.id:
            raise QuoteImageError("Use a message link from this server.")
        channel = interaction.guild.get_channel_or_thread(int(match[2]))
        if channel is None:
            raise QuoteImageError("You can't access that message's channel.")
        user_perms = channel.permissions_for(interaction.user)
        if not (user_perms.view_channel and user_perms.read_message_history):
            raise QuoteImageError("You need channel access and Read Message History to quote a linked message.")
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.read_message_history):
            raise QuoteImageError("I need access and Read Message History in that channel.")
        return await channel.fetch_message(int(match[3]))

    async def attachment_bytes(self, image):
        if image is None:
            return None
        if not (image.content_type or "").startswith("image/") or image.size > MAX_IMAGE_BYTES:
            raise QuoteImageError("Attach an image no larger than 8 MB.")
        data = await image.read()
        # Validate actual bytes before calling the model or rendering, not just MIME metadata.
        await asyncio.to_thread(vision_image, data)
        return data

    async def make_card(self, interaction, text="", image=None, source=None):
        author = source.author if source is not None and text.strip() else interaction.user
        label = "QUOTED MESSAGE" if source is not None and text.strip() else "CUSTOM QUOTE"
        background = await self.attachment_bytes(image)
        if not text.strip():
            if background is None:
                raise QuoteImageError("Provide quote text, a message, or an image to inspire a quote.")
            normalized = await asyncio.to_thread(vision_image, background)
            text = (await self.bot.gateway.narrate(load("persona"),
                "Write one short, original quote inspired by the visible image (at most 35 words). "
                "Return only the quote. Do not claim anyone pictured said it, identify people, "
                "or invent a source or factual backstory.", image_bytes=normalized, image_mime="image/jpeg",
                web_search=False, max_tokens=120)).strip()
            label = "IMAGE-INSPIRED · AI-GENERATED"
        if len(text.strip()) > MAX_QUOTE_CHARS:
            raise QuoteImageError(f"Use at most {MAX_QUOTE_CHARS} quote characters. I won't silently cut the message.")
        avatar = None
        try:
            avatar = await author.display_avatar.with_size(256).with_format("png").read()
        except discord.HTTPException:
            pass  # Renderer provides initials when an avatar can't be fetched.
        card = await asyncio.to_thread(render_quote, text, author.display_name, avatar, background, label)
        await interaction.followup.send(file=discord.File(io.BytesIO(card), filename="zafven-quote.png"),
                                        allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="quote", description="Create a quote image with your profile picture, or quote a real message.")
    @app_commands.guild_only()
    @app_commands.describe(text="Quote text. Blank with an image creates an original image-inspired quote.",
        image="Optional image background (8 MB maximum).", message_link="Optional message link; uses its author's text and avatar.")
    async def quote(self, interaction: discord.Interaction, text: str = "",
                    image: discord.Attachment | None = None, message_link: str = ""):
        await interaction.response.defer(thinking=True)
        try:
            source = None
            if message_link:
                if text:
                    raise QuoteImageError("Use a message link for its original text, or custom text with your own avatar—not both.")
                source = await self.source_message(interaction, message_link)
                text = source.clean_content
                if not image:
                    image = next((a for a in source.attachments if (a.content_type or "").startswith("image/")), None)
            await self.make_card(interaction, text, image, source)
        except (QuoteImageError, discord.HTTPException, GatewayError) as exc:
            log.info("Quote creation unavailable: %s", exc)
            await interaction.followup.send(str(exc) if isinstance(exc, QuoteImageError)
                                            else "I couldn't make that quote image right now. Try again.", ephemeral=True)

    async def quote_message(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(thinking=True)
        try:
            if interaction.guild is None or message.guild is None or interaction.guild.id != message.guild.id:
                raise QuoteImageError("Quote a message in this server.")
            if not message.channel.permissions_for(interaction.user).view_channel:
                raise QuoteImageError("You can't access that message's channel.")
            image = next((a for a in message.attachments if (a.content_type or "").startswith("image/")), None)
            await self.make_card(interaction, message.clean_content, image, message)
        except (QuoteImageError, discord.HTTPException, GatewayError) as exc:
            await interaction.followup.send(str(exc) if isinstance(exc, QuoteImageError)
                                            else "I couldn't make that quote image right now. Try again.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(QuoteCog(bot))
