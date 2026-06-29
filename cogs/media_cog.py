"""/grab — paste a link, zafven pulls the media file and re-uploads it here."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import media

log = logging.getLogger("zafven.media")

DEFAULT_CAP = 8 * 1024 * 1024  # fallback if the guild limit is unknown


class MediaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="grab", description="Paste a link; I'll pull the image/video and post it here.")
    @app_commands.describe(url="A direct image/video link (or a page with preview media).",
                           spoiler="Post it as a spoiler. Default False.")
    @app_commands.guild_only()
    async def grab(self, interaction: discord.Interaction, url: str, spoiler: bool = False) -> None:
        await interaction.response.defer(thinking=True)
        cap = getattr(interaction.guild, "filesize_limit", None) or DEFAULT_CAP

        try:
            filename, data, ctype = await media.grab(url.strip(), cap)
        except media.MediaError as exc:
            if exc.link:
                # Too big to upload here — give the direct link to download instead.
                await interaction.followup.send(
                    f"📎 {exc} I can't post it here, but you can download it directly:\n{exc.link}")
            else:
                await interaction.followup.send(f"❌ {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("grab failed: %s", exc)
            await interaction.followup.send("❌ Couldn't grab that link.")
            return

        if spoiler and not filename.startswith("SPOILER_"):
            filename = "SPOILER_" + filename
        try:
            await interaction.followup.send(
                content=f"📥 from <{url.strip()}>",
                file=discord.File(io.BytesIO(data), filename=filename))
        except discord.HTTPException as exc:
            await interaction.followup.send(f"❌ Discord rejected the upload ({exc.text if hasattr(exc, 'text') else 'too large?'}).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MediaCog(bot))
