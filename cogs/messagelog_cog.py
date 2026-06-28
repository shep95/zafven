"""Logs deleted messages to a moderator channel.

For each deletion it records: the content, who sent it, which channel, the send +
deletion timestamps, whether it was a reply (and to whom), and — via the audit
log — whether the *author* deleted it or a *moderator* did.

Notes:
- Only messages in the bot's cache carry content, so very old messages may log
  as "(content not cached)".
- Attributing the deleter needs the **View Audit Log** permission. Discord only
  audit-logs deletions done by someone *other than* the author, so "no audit
  entry" is treated as a self-delete.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("zafven.messagelog")


class MessageLogCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._audit_counts: dict[int, int] = {}  # audit entry id -> last seen count

    async def _get_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        existing = discord.utils.get(guild.text_channels, name=config.DELETED_LOG_CHANNEL)
        if existing:
            return existing
        if not guild.me.guild_permissions.manage_channels:
            return None
        try:
            return await guild.create_text_channel(config.DELETED_LOG_CHANNEL, reason="zafven deleted-message log")
        except discord.HTTPException:
            return None

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not config.MESSAGE_LOG_ENABLED:
            return
        if message.guild is None or message.author.bot:
            return

        channel = await self._get_channel(message.guild)
        if not channel or channel.id == message.channel.id:
            return

        deleter_kind, deleter = await self._who_deleted(message)
        now = discord.utils.utcnow()

        embed = discord.Embed(
            title="🗑️ Message Deleted",
            color=discord.Color.dark_red(),
            timestamp=now,
        )
        embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Channel", value=message.channel.mention)
        embed.add_field(name="Deleted by", value=self._deleter_label(deleter_kind, deleter, message.author))

        content = message.content or "*(no text — attachment or embed only)*"
        if message.attachments:
            content += "\n📎 " + ", ".join(a.filename for a in message.attachments)
        embed.add_field(name="Content", value=content[:1024], inline=False)

        embed.add_field(name="Reply?", value=self._reply_label(message), inline=False)
        embed.add_field(name="Sent", value=f"<t:{int(message.created_at.timestamp())}:F>")
        embed.add_field(name="Deleted", value=f"<t:{int(now.timestamp())}:F>")
        embed.set_footer(text=f"Message ID: {message.id}")
        await channel.send(embed=embed)

    @staticmethod
    def _deleter_label(kind: str, deleter: discord.abc.User | None, author: discord.abc.User) -> str:
        if kind == "moderator" and deleter:
            return f"🛡️ {deleter.mention} (moderator)"
        if kind == "self":
            return "👤 The author (themselves)"
        return "❔ Unknown (no audit access)"

    @staticmethod
    def _reply_label(message: discord.Message) -> str:
        ref = message.reference
        if ref is None:
            return "No — standalone message"
        resolved = ref.resolved
        if isinstance(resolved, discord.Message):
            return f"Yes — replying to {resolved.author.mention}"
        return f"Yes — replying to message `{ref.message_id}` (original unavailable)"

    async def _who_deleted(self, message: discord.Message) -> tuple[str, discord.abc.User | None]:
        guild = message.guild
        assert guild is not None
        if not guild.me.guild_permissions.view_audit_log:
            return ("unknown", None)

        await asyncio.sleep(1.2)  # let the audit log populate
        try:
            async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.message_delete):
                if not entry.target or entry.target.id != message.author.id:
                    continue
                count = getattr(entry.extra, "count", 1) or 1
                prev = self._audit_counts.get(entry.id)
                self._audit_counts[entry.id] = count
                recent = (discord.utils.utcnow() - entry.created_at).total_seconds() < 20
                if entry.user and entry.user.id != message.author.id:
                    if prev is None and recent:
                        return ("moderator", entry.user)
                    if prev is not None and count > prev:
                        return ("moderator", entry.user)
        except discord.HTTPException:
            return ("unknown", None)
        return ("self", message.author)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageLogCog(bot))
