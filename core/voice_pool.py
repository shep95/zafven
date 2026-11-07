"""Route primary-bot voice commands to separate authorized bot accounts."""
from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace

import discord
from discord import app_commands


class ResponseProxy:
    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original.response, name)

    async def defer(self, **kwargs):
        if not self.original.response.is_done():
            return await self.original.response.defer(**kwargs)

    async def send_message(self, *args, **kwargs):
        if self.original.response.is_done():
            return await self.original.followup.send(*args, **kwargs)
        return await self.original.response.send_message(*args, **kwargs)


class MemberProxy:
    def __init__(self, original, guild):
        self.original = original
        self.guild = guild

    def __getattr__(self, name):
        return getattr(self.original, name)

    @property
    def voice(self):
        state = getattr(self.original, "voice", None)
        if state is None or state.channel is None:
            return None
        channel = self.guild.get_channel(state.channel.id)
        return SimpleNamespace(channel=channel)


class InteractionProxy:
    """Use worker guild/channel state while acknowledging the original interaction."""
    def __init__(self, original, worker):
        self.original = original
        self.client = worker
        self.guild = worker.get_guild(original.guild.id)
        self.user = MemberProxy(original.user, self.guild)
        self.channel = self.guild.get_channel_or_thread(original.channel_id)
        self.response = ResponseProxy(original)

    def __getattr__(self, name):
        return getattr(self.original, name)


class VoicePool:
    def __init__(self, primary):
        self.primary = primary
        self.bots = [primary]
        self._allocation = asyncio.Lock()
        self._leases = {}  # (bot identity,guild ID) -> {channel_id, pending}
        self._operations = {}

    def add(self, bot):
        if bot not in self.bots:
            self.bots.append(bot)
        bot.voice_pool = self

    def operation(self, bot, guild_id):
        return self._operations.setdefault((id(bot), guild_id), asyncio.Lock())

    def ready(self, bot, guild_id):
        if not bot.is_ready():
            return False
        music = bot.get_cog("MusicCog")
        return music is None or not music._restoring_all or guild_id in music._restore_ready

    def occupied_channel(self, bot, guild):
        client = guild.voice_client
        if client is not None and client.channel is not None and client.is_connected():
            return client.channel.id
        lease = self._leases.get((id(bot), guild.id))
        if lease:
            return lease["channel_id"]
        music = bot.get_cog("MusicCog")
        state = music._states.get(guild.id) if music is not None else None
        if state and state.stay:
            return state.home_channel_id
        return None

    async def select(self, interaction):
        guild_id = interaction.guild.id
        state = getattr(interaction.user, "voice", None)
        channel_id = state.channel.id if state and state.channel else None
        async with self._allocation:
            candidates = []
            for bot in self.bots:
                guild = bot.get_guild(guild_id) if self.ready(bot, guild_id) else None
                if guild is not None:
                    candidates.append((bot, guild, self.occupied_channel(bot, guild)))
            if not candidates:
                return None, "No voice account is ready in this server. Check /voicebots and invite a configured helper."
            chosen = None
            if channel_id is not None:
                chosen = next((row for row in candidates if row[2] == channel_id), None)
                if chosen is None:
                    for row in candidates:
                        channel = row[1].get_channel(channel_id)
                        if channel is None or row[2] is not None:
                            continue
                        permissions = channel.permissions_for(row[1].me)
                        if permissions.connect and permissions.speak:
                            chosen = row
                            break
                if chosen is None:
                    return None, ("All available voice accounts are busy or lack Connect/Speak here. "
                                  "Use /voicebots to add another helper; existing sessions will stay in place.")
            else:
                active = [row for row in candidates if row[2] is not None]
                if len(active) > 1:
                    return None, "Join the voice channel you want to control so I can select the right session."
                chosen = active[0] if active else candidates[0]
                channel_id = chosen[2]
            bot = chosen[0]
            key = (id(bot), guild_id)
            lease = self._leases.setdefault(key, {"channel_id": channel_id, "pending": 0})
            if lease["channel_id"] is None:
                lease["channel_id"] = channel_id
            lease["pending"] += 1
            return bot, None

    async def release(self, bot, guild_id):
        async with self._allocation:
            key = (id(bot), guild_id)
            lease = self._leases.get(key)
            if lease:
                lease["pending"] -= 1
                if lease["pending"] <= 0:
                    self._leases.pop(key, None)

    def connected(self, guild_id, channel_id):
        for bot in self.bots:
            guild = bot.get_guild(guild_id) if bot.is_ready() else None
            vc = guild.voice_client if guild else None
            if vc and vc.is_connected() and vc.channel and vc.channel.id == channel_id:
                return bot
        return None

    async def speak_reply(self, guild, user_id, text):
        member = guild.get_member(user_id)
        state = member.voice if member else None
        if state is None or state.channel is None:
            return
        bot = self.connected(guild.id, state.channel.id)
        if bot is not None:
            voice = bot.get_cog("VoiceCog")
            if voice is not None:
                await voice.maybe_speak(bot.get_guild(guild.id), text)


def voice_command(function):
    """Keep native command parsing; route the bound command body after its checks."""
    @wraps(function)
    async def wrapped(self, interaction, *args, **kwargs):
        pool = getattr(self.bot, "voice_pool", None)
        if not isinstance(pool, VoicePool) or self.bot is not pool.primary:
            return await function(self, interaction, *args, **kwargs)
        worker, error = await pool.select(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        try:
            target = worker.get_cog(type(self).__name__)
            if target is None:
                await ResponseProxy(interaction).send_message("This voice account is not ready for that command.", ephemeral=True)
                return
            proxy = InteractionProxy(interaction, worker)
            return await function(target, proxy, *args, **kwargs)
        finally:
            await pool.release(worker, interaction.guild.id)
    return wrapped


def voice_connection(function):
    """Serialize connection changes, without blocking /stop behind long playback."""
    @wraps(function)
    async def wrapped(self, context, *args, **kwargs):
        pool = getattr(self.bot, "voice_pool", None)
        if isinstance(pool, VoicePool):
            guild = getattr(context, "guild", context)
            async with pool.operation(self.bot, guild.id):
                return await function(self, context, *args, **kwargs)
        return await function(self, context, *args, **kwargs)
    return wrapped
