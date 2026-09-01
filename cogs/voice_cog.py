"""Voice — Zafven joins a VC and speaks (Gemini TTS).

She joins your voice channel and can speak her chat replies aloud. Playback is
text → Gemini TTS → FFmpeg → the call, using the standard discord.py voice client.

The old experimental two-way "listen to your mic" mode (which needed the alpha
`discord-ext-voice-recv` extension and swapped in a non-standard voice client) was
removed — it destabilised voice connections on many hosts, causing commands to
hang. Speaking is unaffected.

Runtime needs: PyNaCl (discord.py[voice]) + ffmpeg (nixpacks.toml) + libopus.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import voice_audio, textsplit

log = logging.getLogger("zafven.voice")

TTS_CHUNK = 1200
CONNECT_TIMEOUT = 20.0
DISCONNECT_TIMEOUT = 15.0


class VoiceCog(commands.Cog):
    vc = app_commands.Group(name="vc", description="Voice-chat controls.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._speak: dict[int, bool] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def _ensure_connected(self, interaction: discord.Interaction):
        """Join/move to the caller's VC using the standard voice client. (vc, error)."""
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            return None, "join a voice channel first, then call me in."
        channel = voice.channel
        existing = interaction.guild.voice_client
        try:
            if existing and existing.channel == channel:
                return existing, None
            if existing:
                return None, (
                    f"I'm already connected to **{existing.channel.name}** in this server. "
                    "Discord allows one voice connection per bot account per server; "
                    "I can be in multiple servers at once, but not two VCs in this server."
                )
            return await channel.connect(timeout=CONNECT_TIMEOUT, reconnect=True), None
        except asyncio.TimeoutError:
            return None, "voice connection timed out — try again in a moment."
        except discord.ClientException as exc:
            return None, f"couldn't join ({exc})."
        except Exception as exc:  # noqa: BLE001 — PyNaCl/opus missing, etc.
            return None, f"voice isn't available ({exc.__class__.__name__}). is PyNaCl/ffmpeg installed?"

    # ── commands ─────────────────────────────────────────────────────────
    @vc.command(name="join", description="Bring Zafven into your voice channel.")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        client, err = await self._ensure_connected(interaction)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return
        self._speak[interaction.guild.id] = True
        await interaction.followup.send(
            f"🎙️ I'm in **{client.channel.name}** — talk to me in chat and I'll answer out loud. "
            "Use `/vc speak off` to keep me quiet, or `/play` for music.",
            ephemeral=True)

    @vc.command(name="leave", description="Disconnect Zafven from voice.")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        client = interaction.guild.voice_client
        if not client:
            await interaction.response.send_message("I'm not in a call.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.wait_for(client.disconnect(force=True), timeout=DISCONNECT_TIMEOUT)
        except (discord.HTTPException, asyncio.TimeoutError):
            pass
        self._speak.pop(interaction.guild.id, None)
        await interaction.followup.send("👋 Left the call.", ephemeral=True)

    @vc.command(name="speak", description="Toggle whether Zafven speaks her chat replies in the call.")
    @app_commands.describe(on="True to speak replies aloud, False to stay quiet.")
    @app_commands.guild_only()
    async def speak(self, interaction: discord.Interaction, on: bool) -> None:
        self._speak[interaction.guild.id] = on
        await interaction.response.send_message(
            f"🔊 Speaking replies: **{'on' if on else 'off'}**.", ephemeral=True)

    @app_commands.command(name="say", description="Have Zafven say something out loud in the call.")
    @app_commands.describe(text="What she should say.")
    @app_commands.guild_only()
    async def say(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.defer(ephemeral=True)
        client, err = await self._ensure_connected(interaction)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return
        ok = await self._speak_text(interaction.guild, text)
        await interaction.followup.send("🗣️ Said it." if ok else "🔌 Voice engine hiccupped — try again.",
                                        ephemeral=True)

    # ── speaking ─────────────────────────────────────────────────────────
    async def maybe_speak(self, guild: discord.Guild, text: str) -> None:
        if not self._speak.get(guild.id) or guild.voice_client is None:
            return
        # Keep the channel music-only while a track is playing/queued — don't talk over it.
        music = self.bot.get_cog("MusicCog")
        if music is not None and music.is_active(guild.id):  # type: ignore[attr-defined]
            return
        await self._speak_text(guild, text)

    async def _speak_text(self, guild: discord.Guild, text: str) -> bool:
        client = guild.voice_client
        if client is None:
            return False
        async with self._lock(guild.id):
            if client.is_playing():
                client.stop()
            for chunk in textsplit.chunk(text, limit=TTS_CHUNK, max_chunks=8):
                try:
                    pcm, rate = await self.bot.gateway.tts(chunk)  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001 — gateway/TTS failure must not wedge voice
                    log.warning("TTS failed: %s", exc)
                    return False
                if not await self._play_wav(client, voice_audio.pcm_to_wav(pcm, rate)):
                    return False
        return True

    async def _play_wav(self, client: discord.VoiceClient, wav: bytes) -> bool:
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(wav)
        done = asyncio.Event()

        def after(err: Exception | None) -> None:
            if err:
                log.warning("playback error: %s", err)
            self.bot.loop.call_soon_threadsafe(done.set)

        try:
            client.play(discord.FFmpegPCMAudio(path), after=after)
            # Never wait forever — cap at 5 minutes so a stuck stream can't hold the lock.
            await asyncio.wait_for(done.wait(), timeout=300)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("play failed: %s", exc)
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
