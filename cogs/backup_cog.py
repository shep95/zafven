"""Store server messages locally and mirror JSONL batches to private daily channels."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.community_db import database
from core.user_memory import is_memory_channel

log = logging.getLogger("zafven.backup")


def internal_channel(channel) -> bool:
    parent = getattr(channel, "parent", None)
    category = getattr(channel, "category", None) or getattr(parent, "category", None)
    name = getattr(channel, "name", "")
    return (is_memory_channel(channel) or name in {config.DATA_CHANNEL, config.DELETED_LOG_CHANNEL, config.MOD_ALERT_CHANNEL}
            or (category is not None and (
                category.name == config.MESSAGE_BACKUP_CATEGORY
                or category.name.startswith(config.MESSAGE_BACKUP_CATEGORY + "-"))))


def snapshot(message: discord.Message, event: str = "sent") -> dict:
    return {
        "event": event, "guild_id": message.guild.id, "channel_id": message.channel.id,
        "channel_name": message.channel.name, "message_id": message.id,
        "author_id": message.author.id, "author": str(message.author),
        "author_bot": message.author.bot, "content": message.content,
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "reply_to": message.reference.message_id if message.reference else None,
        "attachments": [{"id": a.id, "name": a.filename, "size": a.size,
                         "content_type": a.content_type, "url": a.url,
                         "proxy_url": a.proxy_url} for a in message.attachments],
        "embeds": [e.to_dict() for e in message.embeds],
        "stickers": [{"id": s.id, "name": s.name, "url": str(s.url)} for s in message.stickers],
        "type": str(message.type), "pinned": message.pinned,
    }


class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = database
        self._channel_lock = asyncio.Lock()
        self._jobs: dict[int, asyncio.Task] = {}
        self.mirror.start()

    def cog_unload(self):
        self.mirror.cancel()
        for task in self._jobs.values():
            task.cancel()

    async def _record(self, message, event="sent"):
        if message.guild is None or internal_channel(message.channel):
            return
        await self.db.archive(snapshot(message, event))
        if not message.author.bot:
            await self.db.remember(message.guild.id, message.author.id, str(message.author),
                                   present=message.guild.get_member(message.author.id) is not None,
                                   source="message")

    @commands.Cog.listener()
    async def on_message(self, message):
        if config.MESSAGE_BACKUP_ENABLED:
            await self._record(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if not config.MESSAGE_BACKUP_ENABLED or not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
        if channel is None or internal_channel(channel):
            return
        # The raw payload preserves uncached edits, including partial updates.
        await self.db.archive({"event": "edit", "guild_id": payload.guild_id,
                               "channel_id": payload.channel_id, "message_id": payload.message_id,
                               "data": payload.data})

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if not config.MESSAGE_BACKUP_ENABLED or not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
        if channel is None or internal_channel(channel):
            return
        await self.db.archive({"event": "deleted", "guild_id": payload.guild_id,
                               "channel_id": payload.channel_id, "message_id": payload.message_id})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        for message_id in payload.message_ids:
            item = type("Deletion", (), {"guild_id": payload.guild_id,
                        "channel_id": payload.channel_id, "message_id": message_id})()
            await self.on_raw_message_delete(item)

    async def _destination(self, guild, day):
        async with self._channel_lock:
            private = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                      attach_files=True, read_message_history=True),
            }
            name = f"messages-{day}"
            categories = [c for c in guild.categories if c.name == config.MESSAGE_BACKUP_CATEGORY
                          or c.name.startswith(config.MESSAGE_BACKUP_CATEGORY + "-")]
            channel = next((ch for c in categories for ch in c.text_channels if ch.name == name), None)
            if channel is None:
                category = next((c for c in categories if len(c.channels) < 50), None)
                if category is None:
                    suffix = f"-{len(categories) + 1}" if categories else ""
                    category = await guild.create_category(config.MESSAGE_BACKUP_CATEGORY + suffix,
                        overwrites=private, reason="Private message backup archive")
                channel = await guild.create_text_channel(name, category=category, overwrites=private,
                    topic="Administrator message archive. JSONL text/metadata; attachment URLs are not file copies.",
                    reason="Daily message backup")
            elif channel.overwrites != private:
                # Never reuse an accidentally public archive channel as-is.
                await channel.edit(overwrites=private, reason="Keep message backups administrator-only")
            return channel

    @tasks.loop(seconds=3)
    async def mirror(self):
        if not config.MESSAGE_BACKUP_ENABLED:
            return
        try:
            day = datetime.now(timezone.utc).date().isoformat()
            for guild in self.bot.guilds:
                batch = await self.db.pending_messages(guild_id=guild.id)
                if not batch:
                    continue
                try:
                    channel = await self._destination(guild, day)
                    data = "\n".join(row["payload"] for row in batch).encode("utf-8")
                    await channel.send(content=f"Message archive · {len(batch)} event(s)",
                        file=discord.File(io.BytesIO(data), filename=f"messages-{batch[0]['id']}-{batch[-1]['id']}.jsonl"),
                        allowed_mentions=discord.AllowedMentions.none())
                    await self.db.mark_mirrored([row["id"] for row in batch])
                except discord.HTTPException:
                    log.exception("Backup mirror failed for %s; database records retained", guild.id)
        except Exception:
            log.exception("Backup mirror iteration failed; will retry")

    @mirror.before_loop
    async def before_mirror(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="backup_history", description="Archive readable message history and discover former members.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(limit="Messages per channel/thread; 0 = all available history.")
    async def backup_history(self, interaction: discord.Interaction, limit: int = 0):
        if limit < 0:
            await interaction.response.send_message("Use 0 for all history, or a positive message count.", ephemeral=True)
            return
        if not config.MESSAGE_BACKUP_ENABLED:
            await interaction.response.send_message("Message backups are disabled in configuration.", ephemeral=True)
            return
        if interaction.guild.id in self._jobs:
            await interaction.response.send_message("A history scan is already running for this server.", ephemeral=True)
            return
        await interaction.response.send_message("History archive started. Use /backup_status to check progress.", ephemeral=True)
        self._jobs[interaction.guild.id] = asyncio.create_task(self._history(interaction.guild, limit))

    async def _history(self, guild, limit):
        try:
            channels = list(guild.text_channels) + list(guild.threads)
            for channel in list(guild.text_channels):
                if internal_channel(channel) or not channel.permissions_for(guild.me).read_message_history:
                    continue
                try:
                    async for thread in channel.archived_threads(limit=None):
                        channels.append(thread)
                except discord.HTTPException:
                    log.warning("Cannot enumerate archived threads in %s", channel.id)
            for channel in {c.id: c for c in channels}.values():
                if internal_channel(channel):
                    continue
                perms = channel.permissions_for(guild.me)
                if not (perms.view_channel and perms.read_message_history):
                    continue
                try:
                    async for message in channel.history(limit=limit or None, oldest_first=True):
                        await self._record(message)
                except discord.HTTPException:
                    log.exception("History channel skipped: %s", channel.id)
        except Exception:
            log.exception("History archive failed in %s", guild.id)
        finally:
            self._jobs.pop(guild.id, None)

    @app_commands.command(name="backup_status", description="Check message archive and history scan status.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def backup_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        def counts(c):
            return tuple(c.execute("SELECT COUNT(*),SUM(mirrored=0) FROM messages WHERE guild_id=?",
                                   (str(interaction.guild.id),)).fetchone())
        total, pending = await self.db._call(counts)
        running = interaction.guild.id in self._jobs
        await interaction.followup.send(f"Stored: {total} events. Pending channel copies: {pending or 0}. "
                                        f"History scan running: {running}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(BackupCog(bot))
