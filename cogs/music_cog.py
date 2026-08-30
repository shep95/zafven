"""Music — Zafven joins a voice channel and plays audio from YouTube / search.

`/play <url or search>` joins your VC, resolves the audio with yt-dlp, streams it
through FFmpeg, and queues anything you add while a track is playing. `/skip`,
`/pause`, `/resume`, `/queue`, `/nowplaying`, `/volume`, and `/stop` (stop + leave)
round it out.

Runtime needs: FFmpeg + PyNaCl (already required for voice) and `yt-dlp`.
Note: this shares the one voice client with `/vc` TTS — if speak-mode is on it can
talk over the music, so use `/vc speak off` (or a music-only bot) for pure playback.
"""
from __future__ import annotations

import asyncio
import collections
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import music

log = logging.getLogger("zafven.music")


class _GuildState:
    __slots__ = ("queue", "current", "lock", "channel_id", "volume", "loop_mode", "skip_flag")

    def __init__(self) -> None:
        self.queue: collections.deque[music.Track] = collections.deque()
        self.current: music.Track | None = None
        self.lock = asyncio.Lock()
        self.channel_id: int | None = None   # where to post "now playing"
        self.volume: float = 1.0
        self.loop_mode: str = "off"          # off | track | queue
        self.skip_flag: bool = False         # set by /skip so a loop doesn't replay it


class MusicError(Exception):
    """Reserved for future explicit failures."""


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._states: dict[int, _GuildState] = {}

    def _state(self, guild_id: int) -> _GuildState:
        return self._states.setdefault(guild_id, _GuildState())

    def is_active(self, guild_id: int) -> bool:
        """True if music is playing or queued — used to keep the VC music-only."""
        st = self._states.get(guild_id)
        return bool(st and (st.current is not None or st.queue))

    async def _connect(self, interaction: discord.Interaction):
        """Join the caller's voice channel (or move to it). Returns (vc, error)."""
        voice = getattr(interaction.user, "voice", None)
        if not voice or not voice.channel:
            return None, "join a voice channel first, then call me in."
        channel = voice.channel
        vc = interaction.guild.voice_client
        try:
            if vc and vc.channel == channel:
                return vc, None
            if vc:
                await vc.move_to(channel)
                return vc, None
            return await channel.connect(), None
        except discord.ClientException as exc:
            return None, f"couldn't join ({exc})."
        except Exception as exc:  # noqa: BLE001 — PyNaCl/ffmpeg missing, etc.
            return None, f"voice isn't available ({exc.__class__.__name__}). is PyNaCl/ffmpeg installed?"

    # ── playback engine ──────────────────────────────────────────────────
    async def _start_next(self, guild: discord.Guild) -> music.Track | None:
        """Pop the next track and start playing it. Returns the track, or None if idle."""
        state = self._state(guild.id)
        async with state.lock:
            vc = guild.voice_client
            if vc is None:
                state.current = None
                return None
            if not state.queue:
                state.current = None
                return None
            track = state.queue.popleft()
            state.current = track
            try:
                source = discord.FFmpegPCMAudio(
                    track.stream_url,
                    before_options=music.FFMPEG_BEFORE_OPTIONS,
                    options=music.FFMPEG_OPTIONS)
                source = discord.PCMVolumeTransformer(source, volume=state.volume)
            except Exception as exc:  # noqa: BLE001 — bad stream / ffmpeg missing
                log.warning("failed to build audio source: %s", exc)
                state.current = None
                # Skip the bad track and try the next one.
                self.bot.loop.create_task(self._start_next(guild))
                return None

            def _after(err: Exception | None) -> None:
                if err:
                    log.warning("playback error in %s: %s", guild.id, err)
                self.bot.loop.call_soon_threadsafe(
                    lambda: self.bot.loop.create_task(self._on_track_end(guild)))

            vc.play(source, after=_after)
            return track

    async def _on_track_end(self, guild: discord.Guild) -> None:
        state = self._state(guild.id)
        # Decide what happens to the track that just finished, based on loop mode.
        finished = state.current
        skipping = state.skip_flag
        state.skip_flag = False
        if finished is not None:
            if state.loop_mode == "track" and not skipping:
                state.queue.appendleft(finished)   # replay the same song
            elif state.loop_mode == "queue":
                state.queue.append(finished)        # send it to the back of the rotation
        track = await self._start_next(guild)
        channel = guild.get_channel(state.channel_id) if state.channel_id else None
        if track is not None and isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(embed=self._now_playing_embed(track))
            except discord.HTTPException:
                pass
        elif track is None and isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send("✅ queue finished — use `/play` for more, or `/stop` to clear off.")
            except discord.HTTPException:
                pass

    def _now_playing_embed(self, track: music.Track) -> discord.Embed:
        embed = discord.Embed(
            title="🎵 now playing",
            description=f"**[{track.title}]({track.webpage_url})**",
            color=discord.Color.purple())
        embed.add_field(name="length", value=music.fmt_duration(track.duration))
        if track.uploader:
            embed.add_field(name="channel", value=track.uploader[:100])
        embed.add_field(name="requested by", value=track.requester)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    # ── commands ─────────────────────────────────────────────────────────
    async def _enqueue(self, interaction: discord.Interaction, query: str, *, front: bool) -> None:
        """Shared body for /play and /playnext. `front=True` jumps the queue."""
        if not config.MUSIC_ENABLED:
            await interaction.response.send_message("🎵 music is disabled on this server.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        vc, err = await self._connect(interaction)
        if err:
            await interaction.followup.send(f"❌ {err}")
            return

        state = self._state(interaction.guild.id)
        if len(state.queue) >= config.MUSIC_MAX_QUEUE:
            await interaction.followup.send(f"❌ the queue is full ({config.MUSIC_MAX_QUEUE}).")
            return

        track = await music.resolve(query.strip(), requester=interaction.user.display_name)
        if track is None:
            await interaction.followup.send(
                "❌ couldn't find or load that. try a different link or search — if this keeps "
                "happening on a hosted bot, YouTube may need a `MUSIC_COOKIE_FILE`.")
            return

        state.channel_id = interaction.channel_id
        if front:
            state.queue.appendleft(track)
        else:
            state.queue.append(track)

        # If nothing is playing, kick off playback now.
        if not vc.is_playing() and not vc.is_paused() and state.current is None:
            started = await self._start_next(interaction.guild)
            if started is not None:
                await interaction.followup.send(embed=self._now_playing_embed(started))
                return
        where = "up next" if front else f"position {len(state.queue)} in line"
        await interaction.followup.send(
            f"➕ queued **{track.title}** ({music.fmt_duration(track.duration)}) — {where}.")

    @app_commands.command(name="play", description="Play a song in your voice channel (YouTube link or search).")
    @app_commands.describe(query="A YouTube/URL link, or words to search for.")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await self._enqueue(interaction, query, front=False)

    @app_commands.command(name="playnext", description="Queue a song to play NEXT (jumps the line).")
    @app_commands.describe(query="A YouTube/URL link, or words to search for.")
    @app_commands.guild_only()
    async def playnext(self, interaction: discord.Interaction, query: str) -> None:
        await self._enqueue(interaction, query, front=True)

    @app_commands.command(name="loop", description="Loop the current song, the whole queue, or turn looping off.")
    @app_commands.describe(mode="What to loop.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="off", value="off"),
        app_commands.Choice(name="track (repeat this song)", value="track"),
        app_commands.Choice(name="queue (repeat the whole queue)", value="queue"),
    ])
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        self._state(interaction.guild.id).loop_mode = mode.value
        label = {"off": "off", "track": "🔂 repeating this song", "queue": "🔁 repeating the whole queue"}[mode.value]
        await interaction.response.send_message(f"loop: **{label}**.")

    @app_commands.command(name="shuffle", description="Shuffle the songs waiting in the queue.")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        import random
        state = self._state(interaction.guild.id)
        if len(state.queue) < 2:
            await interaction.response.send_message("not enough songs in the queue to shuffle.", ephemeral=True)
            return
        items = list(state.queue)
        random.shuffle(items)
        state.queue = collections.deque(items)
        await interaction.response.send_message(f"🔀 shuffled **{len(items)}** queued songs.")

    @app_commands.command(name="remove", description="Remove a song from the queue by its position.")
    @app_commands.describe(position="The number shown in /queue.")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: int) -> None:
        state = self._state(interaction.guild.id)
        if position < 1 or position > len(state.queue):
            await interaction.response.send_message("no song at that position — check `/queue`.", ephemeral=True)
            return
        items = list(state.queue)
        gone = items.pop(position - 1)
        state.queue = collections.deque(items)
        await interaction.response.send_message(f"🗑️ removed **{gone.title}** from the queue.")

    @app_commands.command(name="clear", description="Clear the queue (keeps the current song playing).")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        state = self._state(interaction.guild.id)
        n = len(state.queue)
        state.queue.clear()
        await interaction.response.send_message(f"🧹 cleared **{n}** songs from the queue.")

    @app_commands.command(name="skip", description="Skip the current song.")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is None or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("nothing is playing.", ephemeral=True)
            return
        self._state(interaction.guild.id).skip_flag = True  # don't let a track-loop replay it
        vc.stop()  # fires the after-callback, which advances the queue
        await interaction.response.send_message("⏭️ skipped.")

    @app_commands.command(name="pause", description="Pause playback.")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is None or not vc.is_playing():
            await interaction.response.send_message("nothing is playing.", ephemeral=True)
            return
        vc.pause()
        await interaction.response.send_message("⏸️ paused. use `/resume` to keep going.")

    @app_commands.command(name="resume", description="Resume a paused song.")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is None or not vc.is_paused():
            await interaction.response.send_message("nothing is paused.", ephemeral=True)
            return
        vc.resume()
        await interaction.response.send_message("▶️ resumed.")

    @app_commands.command(name="volume", description="Set playback volume (0-200%).")
    @app_commands.describe(percent="Volume percent, 0-200. Default 100.")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, percent: int) -> None:
        percent = max(0, min(percent, 200))
        state = self._state(interaction.guild.id)
        state.volume = percent / 100
        vc = interaction.guild.voice_client
        if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        await interaction.response.send_message(f"🔊 volume set to **{percent}%**.")

    @app_commands.command(name="nowplaying", description="Show the current song.")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        state = self._state(interaction.guild.id)
        if state.current is None:
            await interaction.response.send_message("nothing is playing.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self._now_playing_embed(state.current))

    @app_commands.command(name="queue", description="Show the song queue.")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        state = self._state(interaction.guild.id)
        if state.current is None and not state.queue:
            await interaction.response.send_message("the queue is empty. use `/play`.", ephemeral=True)
            return
        lines = []
        if state.current is not None:
            lines.append(f"**now:** {state.current.title} ({music.fmt_duration(state.current.duration)})")
        for i, t in enumerate(list(state.queue)[:15], 1):
            lines.append(f"**{i}.** {t.title} ({music.fmt_duration(t.duration)}) — {t.requester}")
        extra = len(state.queue) - 15
        if extra > 0:
            lines.append(f"…and **{extra}** more")
        embed = discord.Embed(title="🎶 queue", description="\n".join(lines),
                              color=discord.Color.purple())
        if state.loop_mode != "off":
            embed.set_footer(text=f"loop: {'this song' if state.loop_mode == 'track' else 'whole queue'}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="Stop the music, clear the queue, and leave the channel.")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        state = self._state(interaction.guild.id)
        state.queue.clear()
        state.current = None
        vc = interaction.guild.voice_client
        if vc is not None:
            try:
                if vc.is_playing() or vc.is_paused():
                    vc.stop()
                await vc.disconnect(force=True)
            except discord.HTTPException:
                pass
            await interaction.response.send_message("⏹️ stopped and left the channel.")
        else:
            await interaction.response.send_message("i'm not in a voice channel.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        """Auto-leave and reset when the bot is disconnected or left alone."""
        if member.guild is None:
            return
        vc = member.guild.voice_client
        if vc is None:
            return
        # Everyone else left the bot's channel → clean up.
        humans = [m for m in vc.channel.members if not m.bot]
        if not humans:
            state = self._state(member.guild.id)
            state.queue.clear()
            state.current = None
            try:
                await vc.disconnect(force=True)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
