"""Minimal helper accounts: voice/music only; no duplicate chat or background cogs."""
import logging

import discord
from discord.ext import commands


class VoiceWorker(commands.Bot):
    voice_worker = True

    def __init__(self, gateway):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.gateway = gateway
        self.voice_pool = None

    async def setup_hook(self):
        await self.load_extension("cogs.music_cog")
        await self.load_extension("cogs.voice_cog")
        # Keep commands local for cog dispatch; do not publish duplicate worker menus
        # or alter commands registered by another application deployment.
        self.tree.clear_commands(guild=None)

    async def on_ready(self):
        logging.getLogger("zafven.voice_workers").info("Voice helper ready: %s", self.user.id)
        await self.change_presence(activity=discord.Game(name="Voice helper â€¢ use Zafven's /vc and /play"))
