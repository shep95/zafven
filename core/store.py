"""Persistence via Discord — a per-guild JSON key-value store.

Railway's filesystem is ephemeral, so state (XP, capsules, ciphers) is kept in a
hidden `zafven-data` channel: one marker message per namespace, with the JSON as
a file attachment. Loaded into memory on first use; writes update the message.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import discord

import config

log = logging.getLogger("zafven.store")

_MARKER = "[zafven-store:{ns}]"
_stores: dict[int, "DiscordStore"] = {}
_locks: dict[int, asyncio.Lock] = {}


class DiscordStore:
    def __init__(self, guild: discord.Guild) -> None:
        self.guild = guild
        self.channel: discord.TextChannel | None = None
        self._messages: dict[str, discord.Message] = {}
        self._cache: dict[str, object] = {}
        self._write_lock = asyncio.Lock()  # serialize writes (no duplicate markers / edit races)

    async def init(self) -> None:
        self.channel = await self._get_channel()
        if not self.channel:
            return
        try:
            async for msg in self.channel.history(limit=50):
                if msg.author.id != self.guild.me.id or not msg.content.startswith("[zafven-store:"):
                    continue
                ns = msg.content[len("[zafven-store:"):].rstrip("]")
                if msg.attachments:
                    raw = await msg.attachments[0].read()
                    self._cache[ns] = json.loads(raw.decode("utf-8"))
                    self._messages[ns] = msg
        except discord.HTTPException as exc:
            log.warning("Store init failed in %s: %s", self.guild.name, exc)

    async def _get_channel(self) -> discord.TextChannel | None:
        existing = discord.utils.get(self.guild.text_channels, name=config.DATA_CHANNEL)
        if existing:
            return existing
        me = self.guild.me
        if not me.guild_permissions.manage_channels:
            log.warning("No '%s' channel and missing Manage Channels in %s", config.DATA_CHANNEL, self.guild.name)
            return None
        try:
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            return await self.guild.create_text_channel(
                config.DATA_CHANNEL, overwrites=overwrites, reason="zafven persistent data")
        except discord.HTTPException as exc:
            log.warning("Could not create data channel: %s", exc)
            return None

    def get(self, namespace: str, default: object = None) -> object:
        return self._cache.get(namespace, default)

    async def set(self, namespace: str, data: object) -> None:
        self._cache[namespace] = data
        if not self.channel:
            return
        marker = _MARKER.format(ns=namespace)
        # Serialize writes: a fresh File is built inside the lock (it's consumed on
        # send), and reading/creating the marker message stays atomic so concurrent
        # writers can't spawn duplicate markers or clobber each other's edit.
        async with self._write_lock:
            payload = json.dumps(data, ensure_ascii=False)
            file = discord.File(io.BytesIO(payload.encode("utf-8")), filename=f"{namespace}.json")
            msg = self._messages.get(namespace)
            try:
                if msg:
                    self._messages[namespace] = await msg.edit(content=marker, attachments=[file])
                else:
                    self._messages[namespace] = await self.channel.send(content=marker, file=file)
            except discord.HTTPException as exc:
                log.warning("Store write failed (%s): %s", namespace, exc)


async def get_store(guild: discord.Guild) -> DiscordStore:
    lock = _locks.setdefault(guild.id, asyncio.Lock())
    async with lock:
        store = _stores.get(guild.id)
        if store is None:
            store = DiscordStore(guild)
            await store.init()
            _stores[guild.id] = store
        return store
