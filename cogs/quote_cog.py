"""`/quote` + 'Make it a Quote' — turn a message into a shareable quote image.

Two ways in:
  • right-click (or long-press) any message → Apps → **Make it a Quote** — the
    natural "quote this message" path; it reads that message + its author's avatar.
  • `/quote` — quote a message by link, or quote yourself with given text.

The image is rendered locally (Pillow); no AI, no network beyond fetching the
author's avatar.
"""
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from core import quoteimg

log = logging.getLogger("zafven.quote")

_LINK_RE = re.compile(r"/channels/(\d+)/(\d+)/(\d+)")


async def _avatar_bytes(user: discord.abc.User) -> bytes | None:
    try:
        asset = user.display_avatar.replace(size=512, static_format="png")
        return await asset.read()
    except (discord.HTTPException, discord.NotFound):
        return None


def _handle(user: discord.abc.User) -> str:
    # prefer the modern @username; fall back to name
    uname = getattr(user, "name", "") or ""
    return f"@{uname}" if uname else ""


async def _render_for(message: discord.Message) -> tuple[bytes | None, str]:
    text = (message.clean_content or message.content or "").strip()
    if not text:
        return None, "there's no text in that message to quote (it's an image/embed/sticker only)."
    author = message.author
    avatar = await _avatar_bytes(author)
    png = quoteimg.render_quote(
        avatar, text, author.display_name, _handle(author), footer="made with zafven")
    return png, ""


class QuoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Message context-menu command — the "quote this message" entry point.
        self._menu = app_commands.ContextMenu(name="Make it a Quote", callback=self._quote_message)
        self.bot.tree.add_command(self._menu)

    def cog_unload(self) -> None:
        self.bot.tree.remove_command(self._menu.name, type=self._menu.type)

    # ── context menu: right-click a message → Apps → Make it a Quote ──────
    async def _quote_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        png, err = await _render_for(message)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return
        await interaction.followup.send(
            file=discord.File(_bytesio(png), filename="quote.png"))

    # ── slash: /quote (by message link, or quote yourself) ───────────────
    @app_commands.command(name="quote", description="Make a quote image from a message link, or quote yourself.")
    @app_commands.describe(
        message_link="Link to the message to quote (right-click a message → Copy Message Link).",
        text="Or type the words to quote (uses YOUR name + avatar).")
    @app_commands.guild_only()
    async def quote(self, interaction: discord.Interaction,
                    message_link: str | None = None, text: str | None = None) -> None:
        await interaction.response.defer(thinking=True)

        if message_link:
            m = _LINK_RE.search(message_link)
            if not m:
                await interaction.followup.send(
                    "❌ that doesn't look like a message link. right-click a message → **Copy Message Link**.",
                    ephemeral=True)
                return
            _gid, cid, mid = (int(x) for x in m.groups())
            channel = self.bot.get_channel(cid) or interaction.channel
            try:
                msg = await channel.fetch_message(mid)  # type: ignore[union-attr]
            except (discord.HTTPException, AttributeError):
                await interaction.followup.send("❌ i couldn't fetch that message (gone, or i can't see that channel).",
                                                ephemeral=True)
                return
            png, err = await _render_for(msg)
            if err:
                await interaction.followup.send(f"❌ {err}", ephemeral=True)
                return
            await interaction.followup.send(file=discord.File(_bytesio(png), filename="quote.png"))
            return

        if text and text.strip():
            avatar = await _avatar_bytes(interaction.user)
            png = quoteimg.render_quote(
                avatar, text.strip(), interaction.user.display_name,
                _handle(interaction.user), footer="made with zafven")
            await interaction.followup.send(file=discord.File(_bytesio(png), filename="quote.png"))
            return

        await interaction.followup.send(
            "give me something to quote: either a **message link**, or **text** to put in your own quote. "
            "tip: right-click any message → **Apps → Make it a Quote**.", ephemeral=True)


def _bytesio(data: bytes):
    import io
    return io.BytesIO(data)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuoteCog(bot))
