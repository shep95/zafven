"""Private per-user memory channels, preferences, and multi-purpose saved notes."""
from __future__ import annotations

import asyncio
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.user_memory import memory, is_memory_channel, BUCKETS

log = logging.getLogger("zafven.user_memory")


class UserMemoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.memory = memory
        self._lock = asyncio.Lock()
        self.mirror.start()

    def cog_unload(self):
        self.mirror.cancel()

    async def destination(self, guild, user_id):
        async with self._lock:
            private = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                       guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                             attach_files=True, read_message_history=True)}
            channel = next((ch for ch in guild.text_channels
                            if ch.name == f"memory-{user_id}" and is_memory_channel(ch)), None)
            if channel:
                if channel.overwrites != private:
                    await channel.edit(overwrites=private, reason="Keep personal memory administrator-only")
                return channel
            categories = [category for category in guild.categories
                          if category.name == config.USER_MEMORY_CATEGORY
                          or category.name.startswith(config.USER_MEMORY_CATEGORY + "-")]
            category = next((c for c in categories if len(c.channels) < 50), None)
            if category is None:
                suffix = f"-{len(categories) + 1}" if categories else ""
                category = await guild.create_category(config.USER_MEMORY_CATEGORY + suffix,
                    overwrites=private, reason="Private per-user memory")
            return await guild.create_text_channel(f"memory-{user_id}", category=category, overwrites=private,
                topic="Zafven personal memory. Bot and administrators only. Users: /memory, /adapt, /remember, /forget.",
                reason="Private per-user memory")

    async def mirror_one(self, guild, row):
        channel = await self.destination(guild, row["user_id"])
        marker = f"[zafven-memory:{row['user_id']}]"
        existing = None
        async for message in channel.history(limit=30):
            if message.author.id == guild.me.id and message.content == marker:
                existing = message
                break
        envelope = {"guild_id": row["guild_id"], "user_id": row["user_id"],
                    "revision": row["revision"], "state": json.loads(row["payload"])}
        file = discord.File(io.BytesIO(json.dumps(envelope, ensure_ascii=False).encode("utf-8")), filename="memory.json")
        if existing:
            sent = await existing.edit(content=marker, attachments=[file], allowed_mentions=discord.AllowedMentions.none())
        else:
            sent = await channel.send(marker, file=file, allowed_mentions=discord.AllowedMentions.none())
        await self.memory.acknowledge(row, channel.id, sent.id)

    @tasks.loop(seconds=5)
    async def mirror(self):
        try:
            for guild in self.bot.guilds:
                for row in await self.memory.pending(guild.id):
                    try:
                        await self.mirror_one(guild, row)
                    except discord.HTTPException:
                        log.exception("Personal memory mirror failed; local memory retained")
        except Exception:
            log.exception("Personal memory mirror iteration failed")

    @mirror.before_loop
    async def before_mirror(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="adapt", description="Set how Zafven talks to you, including playful trolling.")
    @app_commands.guild_only()
    @app_commands.choices(banter=[app_commands.Choice(name=n, value=n) for n in ("off", "light", "troll")])
    async def adapt(self, interaction: discord.Interaction, style: str = "", banter: str = ""):
        await interaction.response.defer(ephemeral=True)
        state = await self.memory.load(interaction.guild, interaction.user.id)
        if style.strip():
            await self.memory.preference(interaction.guild.id, interaction.user.id, "style", style.strip())
        if banter:
            await self.memory.preference(interaction.guild.id, interaction.user.id, "banter", banter)
        state = await self.memory.load(interaction.guild, interaction.user.id)
        text = json.dumps(state["preferences"], ensure_ascii=False)[:1800]
        await interaction.followup.send(f"Your preferences: {text or '{}'}\n"
            "Use /memory to inspect or /forget to reset your personal memory.", ephemeral=True)

    @app_commands.command(name="remember", description="Save a personal fact, project, feedback, or note for future chats.")
    @app_commands.guild_only()
    @app_commands.choices(area=[app_commands.Choice(name=n, value=n) for n in BUCKETS])
    async def remember(self, interaction: discord.Interaction, area: str, text: str):
        await interaction.response.defer(ephemeral=True)
        if not text.strip():
            await interaction.followup.send("Provide a note to remember.", ephemeral=True)
            return
        await self.memory.load(interaction.guild, interaction.user.id)
        await self.memory.add(interaction.guild.id, interaction.user.id, area, text)
        await interaction.followup.send(f"Saved to your {area}. Only your memory is changed.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserMemoryCog(bot))
