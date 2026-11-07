"""Learn reusable methods from the configured author's approved public messages."""
from __future__ import annotations

import asyncio
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.asher_patterns import repository, public_source, SYSTEM, PatternError, validate_profile, sample_digest
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.asher_patterns")


class AsherPatternsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.repository = repository
        self._lock = asyncio.Lock()
        self._job = None
        self.refresh.start()

    def cog_unload(self):
        self.refresh.cancel()
        if self._job:
            self._job.cancel()

    async def authorized(self, interaction):
        if interaction.user.id == config.ASHER_USER_ID or await self.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message("Only Asher or the bot's application owner can manage this learner.", ephemeral=True)
        return False

    async def collect(self, guild):
        count = 0
        for channel in list(guild.text_channels) + list(guild.threads):
            if not public_source(channel, guild):
                continue
            try:
                async for message in channel.history(limit=max(20, min(config.ASHER_SCAN_PER_CHANNEL, 2000))):
                    count += int(await self.repository.record(message))
            except discord.HTTPException:
                log.warning("Could not scan Asher source channel %s", channel.id)
        return count

    async def analyze(self):
        async with self._lock:
            # Re-check current public visibility; never draw from private or departed guilds.
            selected = []
            seen = set()
            budget = 0
            for sample in await self.repository.samples():
                guild = self.bot.get_guild(int(sample["guild_id"]))
                channel = guild.get_channel_or_thread(int(sample["channel_id"])) if guild else None
                if channel is None or not public_source(channel, guild):
                    continue
                normalized = " ".join(sample["content"].lower().split())
                if normalized in seen:
                    continue
                if budget + len(sample["content"]) > 75_000:
                    continue
                seen.add(normalized)
                selected.append(sample)
                budget += len(sample["content"])
            if len(selected) < 20:
                raise PatternError("Need at least 20 distinct Asher messages in approved public channels; no new profile was applied.")
            corrections = await self.repository.corrections()
            digest = sample_digest(selected) + json.dumps(corrections, sort_keys=True)
            active = await self.repository.active()
            if active and active.get("sample_digest") == digest:
                return "No source changes; the existing patterns remain active."
            data = [{key: sample[key] for key in ("message_id", "content")} for sample in selected]
            result = await self.bot.gateway.narrate(SYSTEM, json.dumps(
                {"messages": data, "explicit_method_corrections": corrections}, ensure_ascii=False),
                web_search=False, max_tokens=2800, temperature=0.2, use_learned_patterns=False)
            profile = validate_profile(result, selected)
            profile["sample_digest"] = digest
            await self.repository.save(profile)
            return f"Applied {len(profile['patterns'])} provisional methods from {len(selected)} distinct messages."

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id == config.ASHER_USER_ID and message.guild is not None:
            try:
                await self.repository.record(message)
            except Exception:
                log.exception("Asher source recording failed")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.id == config.ASHER_USER_ID and not after.content.strip():
            await self.repository.delete_samples([after.id])
        else:
            await self.on_message(after)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if not payload.guild_id or not await self.repository.has_sample(payload.message_id):
            return
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
        if channel is None or not public_source(channel, guild):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            await self.on_message_edit(None, message)
        except discord.NotFound:
            await self.repository.delete_samples([payload.message_id])
        except discord.HTTPException:
            log.warning("Could not refresh edited Asher message %s", payload.message_id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id:
            await self.repository.delete_samples([payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id:
            await self.repository.delete_samples(payload.message_ids)

    @tasks.loop(hours=12)
    async def refresh(self):
        if not self.repository.db.path.exists():
            return
        sources = []
        for guild in self.bot.guilds:
            if not await self.repository.enabled(guild.id):
                continue
            try:
                await self.collect(guild)
                sources.append(guild)
            except Exception:
                log.exception("Scheduled source collection failed")
        if not sources:
            return
        try:
            result = await self.analyze()
            for guild in sources:
                await self.repository.error(guild.id, "")
            log.info("Asher patterns: %s", result)
        except Exception as exc:
            for guild in sources:
                await self.repository.error(guild.id, str(exc))
            log.warning("Scheduled pattern analysis incomplete: %s", exc)

    @refresh.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="asher_learn", description="Authorize public-message pattern learning for Asher in this server.")
    @app_commands.guild_only()
    async def asher_learn(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        if self._job and not self._job.done():
            await interaction.response.send_message("A pattern scan is already running. Use /asher_status.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.repository.enable(interaction.guild.id, interaction.user.id)
        self._job = asyncio.create_task(self._run(interaction.guild))
        await interaction.followup.send(
            f"Learning enabled for account {config.ASHER_USER_ID} from readable public channels in this server. "
            "Recurring supported methods will guide Zafven across servers; raw messages are not added to replies. "
            "Scanning now; check /asher_status. Refreshes every 12 hours while enabled.", ephemeral=True)

    async def _run(self, guild):
        try:
            await self.collect(guild)
            await self.analyze()
            await self.repository.error(guild.id, "")
        except Exception as exc:
            await self.repository.error(guild.id, str(exc))
            log.warning("Asher learning incomplete: %s", exc)

    @app_commands.command(name="asher_status", description="Inspect the learned methods, evidence IDs, and learner state.")
    @app_commands.guild_only()
    async def asher_status(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        profile = await self.repository.active()
        def status(c):
            row = c.execute("SELECT enabled,last_error FROM asher_sources WHERE guild_id=?", (str(interaction.guild.id),)).fetchone()
            return dict(row) if row else {"enabled": False, "last_error": "Not started"}
        state = await self.repository.db._call(status)
        message = f"Source account: {config.ASHER_USER_ID}. This server: {state}. Scan running: {bool(self._job and not self._job.done())}."
        if profile:
            file = discord.File(io.BytesIO(json.dumps(profile, indent=2, ensure_ascii=False).encode()), filename="asher-patterns.json")
            await interaction.followup.send(message, file=file, ephemeral=True)
        else:
            await interaction.followup.send(message + " No active learned profile.", ephemeral=True)

    @app_commands.command(name="asher_pause", description="Stop collecting Asher samples from this server; retain learned methods.")
    @app_commands.guild_only()
    async def asher_pause(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self.repository.pause(interaction.guild.id)
        await interaction.followup.send("Collection paused here. Existing learned methods remain; /asher_reset removes them globally.", ephemeral=True)

    @app_commands.command(name="asher_correct", description="Correct a shared reasoning method without rewriting source messages.")
    @app_commands.guild_only()
    async def asher_correct(self, interaction: discord.Interaction, topic: str, correction: str):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.repository.correct(topic, correction, interaction.user.id)
        except PatternError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("Method correction saved for the shared profile and future analyses. "
                                        "Original evidence remains unchanged.", ephemeral=True)

    @app_commands.command(name="asher_reset", description="Remove the global learned Asher profile and its dedicated source samples.")
    @app_commands.guild_only()
    async def asher_reset(self, interaction: discord.Interaction):
        if not await self.authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if self._job:
            self._job.cancel()
        async with self._lock:
            await self.repository.reset()
        await interaction.followup.send("Learned Asher methods and dedicated samples removed; collection disabled. General message backups are separate.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AsherPatternsCog(bot))
