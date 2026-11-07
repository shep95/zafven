"""Publish the loaded command tree and retire stale guild-scoped registrations."""
import asyncio
import logging

import discord

log = logging.getLogger("zafven.commands")


class CommandSync:
    def __init__(self, bot, mirror_guild_id=None):
        self.bot = bot
        self.mirror_guild_id = mirror_guild_id
        self.published = False
        self.global_count = 0
        self.checked_guilds = set()
        self.guild_errors = {}
        self._lock = asyncio.Lock()

    async def publish(self):
        async with self._lock:
            expected = self.bot.tree.get_commands()
            if not expected:
                raise RuntimeError("Refusing to publish an empty command tree.")
            # Bulk overwrite updates surviving commands and removes obsolete ones
            # in one request; do not delete everything before recreating commands.
            result = await self.bot.tree.sync()
            desired = {(c.to_dict(self.bot.tree).get("type", 1), c.name) for c in expected}
            received = {(c.type.value, c.name) for c in result}
            if desired != received:
                raise RuntimeError("Discord returned a different command set than the loaded tree.")
            self.published = True
            self.global_count = len(result)
            log.info("Published %d global commands, including context menus", len(result))
            return self.global_count

    async def guild(self, guild, *, force=False):
        async with self._lock:
            if not self.published:
                raise RuntimeError("Publish global commands before reconciling guild commands.")
            if guild.id in self.checked_guilds and not force:
                return False
            if guild.id == self.mirror_guild_id:
                self.bot.tree.clear_commands(guild=guild)
                self.bot.tree.copy_global_to(guild=guild)
                await self.bot.tree.sync(guild=guild)
                changed = True
            else:
                # Read before writing: most public servers have no overrides.
                remote = await self.bot.tree.fetch_commands(guild=guild)
                local = self.bot.tree.get_commands(guild=guild)
                changed = bool(remote or local)
                if changed:
                    # Empty for ordinary servers: removes legacy test copies that
                    # otherwise shadow the updated globals. Explicit code-defined
                    # guild commands are retained if introduced in future cogs.
                    await self.bot.tree.sync(guild=guild)
            self.checked_guilds.add(guild.id)
            self.guild_errors.pop(guild.id, None)
            return changed

    async def guilds(self, *, force=False):
        updated = 0
        for guild in list(self.bot.guilds):
            try:
                updated += int(await self.guild(guild, force=force))
            except discord.DiscordException as error:
                self.guild_errors[guild.id] = type(error).__name__
                log.warning("Command reconciliation failed for guild %s (%s)", guild.id, type(error).__name__)
        return updated
