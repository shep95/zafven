"""Scans images, GIFs, and files on upload and removes unsafe ones.

A bot can't intercept an upload *before* it posts (Discord has no pre-send hook),
so this reacts the instant a message with attachments appears: dangerous file
types and known-malware (VirusTotal hash) are removed immediately; images are
classified by Gemini vision and removed if explicit (skipped in age-gated NSFW
channels). Removals post a public notice and a private mod alert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config
from core import filesafety
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.filescan")

VT_MAX_BYTES = 32 * 1024 * 1024
_CLASSIFIER = (
    "You are a strict content-safety image classifier. Reply with EXACTLY one word: "
    "SAFE or EXPLICIT. EXPLICIT = pornographic nudity, sexual acts, or graphic gore. "
    "Anything else is SAFE."
)


class FileScanCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.FILESCAN_ENABLED or message.author.bot or message.guild is None:
            return
        if not message.attachments:
            return
        if config.FILESCAN_BYPASS_MODS and isinstance(message.author, discord.Member) \
                and message.author.guild_permissions.manage_messages:
            return

        removed: list[tuple[str, str]] = []
        review: list[tuple[str, str]] = []
        max_image = config.FILESCAN_MAX_IMAGE_MB * 1024 * 1024
        nsfw_ok = (config.NSFW_ALLOW_IN_NSFW_CHANNELS
                   and getattr(message.channel, "is_nsfw", lambda: False)())

        for att in message.attachments:
            if filesafety.is_blocked_file(att.filename):
                removed.append(("dangerous file type", att.filename))
                continue

            data: bytes | None = None
            if config.VIRUSTOTAL_API_KEY and att.size <= VT_MAX_BYTES:
                try:
                    data = await att.read()
                    if await filesafety.virustotal_malicious(filesafety.sha256(data)):
                        removed.append(("known malware", att.filename))
                        continue
                except discord.HTTPException:
                    data = None

            if (config.NSFW_SCAN_ENABLED and not nsfw_ok
                    and (att.content_type or "").startswith("image/") and att.size <= max_image):
                if data is None:
                    try:
                        data = await att.read()
                    except discord.HTTPException:
                        continue
                verdict = await self._classify(data, att.content_type)
                if verdict == "explicit":
                    removed.append(("explicit image", att.filename))
                elif verdict == "uncertain":
                    review.append(("image needs review", att.filename))

        if removed:
            await self._enforce(message, removed)
        elif review:
            await self._alert_mods(message, review, deleted=False)

    async def _classify(self, data: bytes, mime: str | None) -> str:
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                _CLASSIFIER, "Classify this image.", image_bytes=data,
                image_mime=mime or "image/png", web_search=False, max_tokens=5)
        except GatewayError:
            return "uncertain"  # safety filter blocked / unreachable → human review
        return "explicit" if "EXPLICIT" in out.upper() else "safe"

    async def _enforce(self, message: discord.Message, removed: list[tuple[str, str]]) -> None:
        if message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        reasons = ", ".join(sorted({r for r, _ in removed}))
        try:
            await message.channel.send(
                f"🛡️ Removed an upload from {message.author.mention} for safety (**{reasons}**). "
                "Don't download files from people you don't trust.")
        except discord.HTTPException:
            pass
        await self._alert_mods(message, removed, deleted=True)
        log.info("File scan removed upload from %s: %s", message.author, removed)

    async def _alert_mods(self, message: discord.Message, items: list[tuple[str, str]],
                          deleted: bool) -> None:
        guild = message.guild
        channel = discord.utils.get(guild.text_channels, name=config.MOD_ALERT_CHANNEL)
        if channel is None and guild.me.guild_permissions.manage_channels:
            try:
                overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                              guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
                channel = await guild.create_text_channel(
                    config.MOD_ALERT_CHANNEL, overwrites=overwrites, reason="zafven mod alerts")
            except discord.HTTPException:
                channel = None
        if channel is None:
            return
        listing = "\n".join(f"• **{r}** — `{fn}`" for r, fn in items)
        embed = discord.Embed(
            title="🚩 File scan" + (" — removed" if deleted else " — needs review"),
            description=listing, color=discord.Color.red() if deleted else discord.Color.orange(),
            timestamp=datetime.now(timezone.utc))
        embed.add_field(name="From", value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Channel", value=message.channel.mention)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FileScanCog(bot))
