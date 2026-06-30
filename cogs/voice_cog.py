"""Voice — Zafven joins a voice channel and speaks (Gemini TTS).

Speaking (text → voice in a VC) is fully supported. When she's in a call with
speak-mode on, her chat replies are spoken aloud too — so people type to her and
she answers by voice. (Two-way *listening* needs a voice-receive extension that
mainline discord.py lacks; that's a separate, harder follow-up.)

Runtime needs: PyNaCl (discord.py[voice]) and the ffmpeg binary (see nixpacks.toml).
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
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.voice")

TTS_CHUNK = 1200  # chars per TTS request


class VoiceCog(commands.Cog):
    vc = app_commands.Group(name="vc", description="Voice-chat controls.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._speak: dict[int, bool] = {}            # guild_id -> auto-speak chat replies
        self._locks: dict[int, asyncio.Lock] = {}    # guild_id -> playback lock

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def _ensure_connected(self, interaction: discord.Interaction) -> tuple[discord.VoiceClient | None, str | None]:
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            return None, "Join a voice channel first, then call me in."
        channel = voice.channel
        existing = interaction.guild.voice_client
        try:
            if existing and existing.channel == channel:
                return existing, None
            if existing:
                await existing.move_to(channel)
                return existing, None
            return await channel.connect(), None
        except discord.ClientException as exc:
            return None, f"Couldn't join ({exc})."
        except Exception as exc:  # noqa: BLE001 — e.g. PyNaCl missing
            return None, f"Voice isn't available ({exc.__class__.__name__}). Is PyNaCl/ffmpeg installed?"

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
            "Use `/vc speak off` to mute my replies, or `/vc leave` to drop.", ephemeral=True)

    @vc.command(name="leave", description="Disconnect Zafven from voice.")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        client = interaction.guild.voice_client
        if client:
            await client.disconnect(force=True)
            self._speak.pop(interaction.guild.id, None)
            await interaction.response.send_message("👋 Left the call.", ephemeral=True)
        else:
            await interaction.response.send_message("I'm not in a call.", ephemeral=True)

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

    # --- used by the chat cog to voice her replies ---
    async def maybe_speak(self, guild: discord.Guild, text: str) -> None:
        if not self._speak.get(guild.id) or guild.voice_client is None:
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
                except GatewayError as exc:
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
            await done.wait()
            return True
        except Exception as exc:  # noqa: BLE001 — ffmpeg missing, etc.
            log.warning("play failed: %s", exc)
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
