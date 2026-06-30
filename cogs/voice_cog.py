"""Voice — Zafven joins a VC, speaks (Gemini TTS), and (experimentally) listens.

SPEAKING is solid: text → Gemini TTS → played in the call. With speak-mode on,
her chat replies are voiced too.

LISTENING (two-way) is EXPERIMENTAL and needs the `discord-ext-voice-recv`
extension (mainline discord.py can't receive audio). When on, she captures each
speaker's audio, sends it to Gemini (which transcribes + replies in one call),
and speaks the answer back. Latency is a few seconds; tune SILENCE/MIN below.

Runtime needs: PyNaCl (discord.py[voice]) + ffmpeg (nixpacks.toml), and for
listening, discord-ext-voice-recv + libopus.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import voice_audio, textsplit
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.voice")

try:
    from discord.ext import voice_recv  # type: ignore
    HAS_RECV = True
except Exception:  # noqa: BLE001
    voice_recv = None  # type: ignore
    HAS_RECV = False

TTS_CHUNK = 1200
RECV_RATE = 48000        # voice_recv delivers 48kHz 16-bit stereo PCM
SILENCE_SEC = 1.2        # gap that marks the end of an utterance
MIN_SEC = 0.8            # ignore utterances shorter than this
MIN_BYTES = int(RECV_RATE * 2 * 2 * MIN_SEC)
MAX_BYTES = RECV_RATE * 2 * 2 * 30  # 30s cap per utterance


class VoiceCog(commands.Cog):
    vc = app_commands.Group(name="vc", description="Voice-chat controls.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._speak: dict[int, bool] = {}
        self._listen: dict[int, bool] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        # listening buffers (written from the recv thread)
        self._buf_lock = threading.Lock()
        self._buffers: dict[tuple[int, int], bytearray] = {}
        self._last: dict[tuple[int, int], float] = {}
        self._busy: set[tuple[int, int]] = set()
        if HAS_RECV:
            self._flush.start()

    def cog_unload(self) -> None:
        if HAS_RECV:
            self._flush.cancel()

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    async def _ensure_connected(self, interaction: discord.Interaction):
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
            cls = voice_recv.VoiceRecvClient if HAS_RECV else discord.VoiceClient
            return await channel.connect(cls=cls), None
        except discord.ClientException as exc:
            return None, f"Couldn't join ({exc})."
        except Exception as exc:  # noqa: BLE001 — PyNaCl missing, etc.
            return None, f"Voice isn't available ({exc.__class__.__name__}). Is PyNaCl/ffmpeg installed?"

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
        hint = " Use `/vc listen on` and I'll respond to your voice too." if HAS_RECV else ""
        await interaction.followup.send(
            f"🎙️ I'm in **{client.channel.name}** — talk to me in chat and I'll answer out loud.{hint}",
            ephemeral=True)

    @vc.command(name="leave", description="Disconnect Zafven from voice.")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        client = interaction.guild.voice_client
        if client:
            with self._buf_lock:
                for k in [k for k in self._buffers if k[0] == interaction.guild.id]:
                    self._buffers.pop(k, None)
                    self._last.pop(k, None)
            await client.disconnect(force=True)
            self._speak.pop(interaction.guild.id, None)
            self._listen.pop(interaction.guild.id, None)
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

    @vc.command(name="listen", description="Toggle whether Zafven listens and replies to your voice (experimental).")
    @app_commands.describe(on="True to make her respond to what you say out loud.")
    @app_commands.guild_only()
    async def listen(self, interaction: discord.Interaction, on: bool) -> None:
        if not HAS_RECV:
            await interaction.response.send_message(
                "❌ Voice listening isn't installed (needs `discord-ext-voice-recv`).", ephemeral=True)
            return
        client = interaction.guild.voice_client
        if client is None:
            await interaction.response.send_message("Call me in first with `/vc join`.", ephemeral=True)
            return
        self._listen[interaction.guild.id] = on
        try:
            if on:
                if not client.is_listening():
                    client.listen(voice_recv.BasicSink(self._on_voice))
            elif client.is_listening():
                client.stop_listening()
        except Exception as exc:  # noqa: BLE001
            await interaction.response.send_message(f"❌ Couldn't toggle listening ({exc}).", ephemeral=True)
            return
        await interaction.response.send_message(
            f"👂 Listening: **{'on' if on else 'off'}**." + (" Just talk — I'll answer." if on else ""),
            ephemeral=True)

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

    # ── listening pipeline ───────────────────────────────────────────────
    def _on_voice(self, user, data) -> None:  # runs in the recv thread
        try:
            if user is None or getattr(user, "bot", False):
                return
            guild = getattr(user, "guild", None)
            if guild is None:
                return
            client = guild.voice_client
            if client is None or client.is_playing():  # don't capture while she's talking
                return
            pcm = getattr(data, "pcm", None)
            if not pcm:
                return
            key = (guild.id, user.id)
            with self._buf_lock:
                buf = self._buffers.setdefault(key, bytearray())
                if len(buf) < MAX_BYTES:
                    buf.extend(pcm)
                self._last[key] = time.time()
        except Exception:  # noqa: BLE001 — never raise in the recv thread
            pass

    @tasks.loop(seconds=0.4)
    async def _flush(self) -> None:
        now = time.time()
        ready: list[tuple[tuple[int, int], bytes]] = []
        with self._buf_lock:
            for key, last in list(self._last.items()):
                if not self._listen.get(key[0]):
                    continue
                if key in self._busy:
                    continue
                if now - last >= SILENCE_SEC and len(self._buffers.get(key, b"")) >= MIN_BYTES:
                    ready.append((key, bytes(self._buffers.pop(key))))
                    self._last.pop(key, None)
                    self._busy.add(key)
        for key, pcm in ready:
            asyncio.create_task(self._process(key, pcm))

    @_flush.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _process(self, key: tuple[int, int], pcm: bytes) -> None:
        guild_id, user_id = key
        try:
            guild = self.bot.get_guild(guild_id)
            if guild is None or guild.voice_client is None:
                return
            wav = voice_audio.pcm_to_wav(pcm, RECV_RATE, channels=2)
            system = (load_brain("companion") + "\n\nThe user just SPOKE this aloud in a voice call. "
                      "Understand what they said, then reply as Zafven — short and conversational (1-2 "
                      "sentences), because your reply is read OUT LOUD. If you can't make out the audio, "
                      "say you didn't catch that.")
            try:
                reply = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                    system, "Respond to what they just said.",
                    image_bytes=wav, image_mime="audio/wav", web_search=False, max_tokens=220)
            except GatewayError as exc:
                log.warning("voice understand failed: %s", exc)
                return
            await self._speak_text(guild, reply)
        finally:
            with self._buf_lock:
                self._busy.discard(key)

    # ── speaking ─────────────────────────────────────────────────────────
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
