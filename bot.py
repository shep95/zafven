"""zafven - a Discord companion, music, Bible, and server-management bot.

Gemini powers chat, TTS, summaries, and knowledge workflows through a single
ModelGateway. Server features such as music, Bible reference replies, join/leave
logging and manual inactive cleanup work independently of the model.
Automatic content policing is not installed.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

import discord
from discord.ext import commands

import config
from core.model_gateway import ModelGateway
from core.voice_pool import VoicePool
from core.voice_workers import VoiceWorker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("zafven")

INITIAL_COGS = [
    "cogs.vibe_cog",
    "cogs.imagine_cog",
    "cogs.quote_cog",
    "cogs.audit_cog",
    "cogs.tools_cog",
    "cogs.synthesize_cog",
    "cogs.council_cog",
    "cogs.forge_cog",
    "cogs.knowledge_cog",
    "cogs.media_cog",
    "cogs.ranks_cog",
    "cogs.capsule_cog",
    "cogs.mood_cog",
    "cogs.cipher_cog",
    "cogs.bible_cog",
    "cogs.chat_cog",
    "cogs.voice_cog",
    "cogs.voice_pool_cog",
    "cogs.music_cog",
    "cogs.culture_cog",
    "cogs.brain_cog",
    "cogs.asher_patterns_cog",
    "cogs.teach_cog",
    "cogs.persona_cog",
    "cogs.logging_cog",
    "cogs.messagelog_cog",
    "cogs.backup_cog",
    "cogs.user_memory_cog",
    "cogs.public_bot_cog",
    "cogs.reinvite_cog",
    "cogs.moderation_cog",
    "cogs.report_cog",
    "cogs.invites_cog",
    "cogs.help_cog",
]


def _load_opus() -> None:
    """Explicitly load libopus (needed to encode voice audio for playback/TTS).

    discord.py's auto-loader uses find_library, which fails in minimal containers
    even when libopus is installed — so load it directly by filename.
    """
    if discord.opus.is_loaded():
        return
    candidates = [
        "libopus.so.0", "libopus.so", "opus",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
    ]
    for name in candidates:
        try:
            discord.opus.load_opus(name)
            log.info("Loaded libopus via %s", name)
            return
        except Exception:  # noqa: BLE001
            continue
    log.warning("Could not load libopus — voice playback (/say, /play, TTS) may not work.")


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    return intents


class Zafven(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=build_intents(), help_command=None)
        self.gateway = ModelGateway()
        self.voice_pool = VoicePool(self)

    async def setup_hook(self) -> None:
        _load_opus()
        await self.gateway.start()
        self.tree.on_error = self.on_app_command_error
        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:  # noqa: BLE001
                log.exception("Failed to load %s", ext)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally (may take up to 1h)", len(synced))

    async def on_ready(self) -> None:
        log.info("zafven online as %s (id=%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game(name="/help • /houseofasher"))

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: discord.app_commands.AppCommandError) -> None:
        if isinstance(error, discord.app_commands.MissingPermissions):
            await self._respond(interaction, "You don't have permission to use this command.")
            return
        log.exception("Unhandled app-command error", exc_info=error)
        await self._respond(interaction, f"Something went wrong: `{error}`")

    @staticmethod
    async def _respond(interaction: discord.Interaction, content: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await self.gateway.close()
        await super().close()


async def main() -> None:
    problems = config.validate()
    if problems:
        raise SystemExit("Configuration errors:\n  - " + "\n  - ".join(problems)
                         + "\nCopy .env.example to .env (or set Railway Variables) and fill them in.")
    async with AsyncExitStack() as stack:
        bot = await stack.enter_async_context(Zafven())
        primary_task = asyncio.create_task(bot.start(config.TOKEN))
        ready_task = asyncio.create_task(bot.wait_until_ready())
        tasks = [primary_task, ready_task]
        try:
            done, _ = await asyncio.wait((primary_task, ready_task), return_when=asyncio.FIRST_COMPLETED)
            if primary_task in done:
                await primary_task
                return
            await ready_task
            for index, token in enumerate(config.VOICE_BOT_TOKENS, 1):
                worker = await stack.enter_async_context(VoiceWorker(bot.gateway))
                bot.voice_pool.add(worker)
                task = asyncio.create_task(worker.start(token))
                tasks.append(task)
                task.add_done_callback(lambda task, index=index: _worker_finished(task, index))
            await primary_task
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _worker_finished(task, index):
    if not task.cancelled() and task.exception() is not None:
        # Log only the class, never token-bearing configuration or request data.
        log.error("Voice helper %s stopped (%s); other accounts remain available.",
                  index, type(task.exception()).__name__)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
