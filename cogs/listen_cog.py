"""`/listen` — control layer for the acoustic-observation platform.

The bot is the control + storage + search + audit surface. It does NOT read your
microphone: capture happens in a separate authorized client that shows a recording
indicator and ingests data here. Starting a session is consent-gated — the operator
must acknowledge the legal notice before a session can go ACTIVE, because recording
other people may require their consent depending on where you are.

With no transcription engine configured (the default), sessions run but produce no
transcripts — status says so honestly rather than inventing content.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import store as store_mod
from core.listen import ListenController, ENGINES
from core.listen.retention import RetentionPolicy
from core.listen.session import SessionState, TransitionError

log = logging.getLogger("zafven.listen")

_LEGAL_NOTICE = (
    "⚖️ **before you record — read this.** this captures audio from your own "
    "authorized device and stores it for you. recording other people can require "
    "their consent depending on where you live (many places are all-party consent, "
    "and laws vary). you are responsible for using it lawfully. the capture client "
    "always shows a visible recording indicator, and you can stop anytime with "
    "`/listen stop`. type `/listen consent` to acknowledge and begin."
)


async def _ctl(guild: discord.Guild) -> ListenController:
    return ListenController(await store_mod.get_store(guild))


class ListenCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    listen = app_commands.Group(name="listen", description="Authorized audio observation sessions (you control).")

    # ── start / consent / stop ────────────────────────────────────────────
    @listen.command(name="start", description="Create an authorized listening session (consent required to begin).")
    @app_commands.describe(source="What to capture: microphone (default) or system_audio.")
    @app_commands.guild_only()
    async def start(self, interaction: discord.Interaction, source: str = "microphone") -> None:
        if not config.LISTEN_ENABLED:
            await interaction.response.send_message("the listening platform is off.", ephemeral=True)
            return
        source = "system_audio" if source.strip().lower() in {"system", "system_audio"} else "microphone"
        ctl = await _ctl(interaction.guild)
        if ctl.active_session_for(interaction.user.id):
            await interaction.response.send_message(
                "you already have an active session — `/listen status` or `/listen stop`.", ephemeral=True)
            return
        session = await ctl.create_session(interaction.user.id, audio_source=source)
        await ctl.authorize(session)
        await interaction.response.send_message(
            f"🎙️ session `{session.id}` created (source: **{source}**), pending your consent.\n\n{_LEGAL_NOTICE}",
            ephemeral=True)

    @listen.command(name="consent", description="Acknowledge the legal notice and start capture on your authorized client.")
    @app_commands.guild_only()
    async def consent(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        session = ctl.active_session_for(interaction.user.id)
        if session is None:
            await interaction.response.send_message("no pending session — `/listen start` first.", ephemeral=True)
            return
        await ctl.acknowledge_consent(session)
        try:
            await ctl.activate(session)
        except TransitionError as exc:
            await interaction.response.send_message(f"couldn't start: {exc}", ephemeral=True)
            return
        engines = ENGINES.status()
        note = ("" if any(engines.values()) else
                "\n\n⚠️ no transcription engine is configured and no capture client is connected, so this "
                "session won't produce transcripts yet — it's authorized and audited, but capture + "
                "transcription need the external client + engine (see `/listen help`).")
        await interaction.response.send_message(
            f"✅ consent acknowledged. session `{session.id}` is **active**. stop anytime with `/listen stop`.{note}",
            ephemeral=True)

    @listen.command(name="stop", description="Stop your active session.")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        session = ctl.active_session_for(interaction.user.id)
        if session is None:
            await interaction.response.send_message("you have no active session.", ephemeral=True)
            return
        await ctl.stop(session)
        await interaction.response.send_message(
            f"🛑 session `{session.id}` stopped after {session.duration_seconds()}s.", ephemeral=True)

    # ── status / sessions / history ───────────────────────────────────────
    @listen.command(name="status", description="Show your current session state and engine availability.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        session = ctl.active_session_for(interaction.user.id)
        engines = ENGINES.status()
        eng_line = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in engines.items())
        if session is None:
            body = "no active session. `/listen start` to create one."
        else:
            body = (f"session `{session.id}`\nstate: **{session.state}**\n"
                    f"source: {session.audio_source}\ndevice: {session.device_id or '(none reported)'}\n"
                    f"duration: {session.duration_seconds()}s\ncapture client: "
                    f"{session.capture_client or '(none connected)'}")
        await interaction.response.send_message(
            f"🛰️ **listen status**\n{body}\n\nengines: {eng_line}", ephemeral=True)

    @listen.command(name="sessions", description="List your recent sessions.")
    @app_commands.guild_only()
    async def sessions(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        mine = [s for s in (ctl.get_session(sid) for sid in ctl._sessions())  # noqa: SLF001
                if s and s.user_id == interaction.user.id]
        mine.sort(key=lambda s: -s.created_at)
        if not mine:
            await interaction.response.send_message("no sessions yet.", ephemeral=True)
            return
        lines = [f"• `{s.id}` — {s.state}, {s.duration_seconds()}s" for s in mine[:10]]
        await interaction.response.send_message("🗂️ your recent sessions:\n" + "\n".join(lines), ephemeral=True)

    @listen.command(name="history", description="Show recent session events (audit log).")
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        session = ctl.active_session_for(interaction.user.id)
        events = ctl.events(session_id=session.id if session else "", limit=15)
        if not events:
            await interaction.response.send_message("no events recorded yet.", ephemeral=True)
            return
        lines = [f"• {e.event_type} ({e.state_before or '—'}→{e.state_after or '—'})" for e in events]
        await interaction.response.send_message("🧾 recent events:\n" + "\n".join(lines[-15:]), ephemeral=True)

    # ── transcript / search ───────────────────────────────────────────────
    @listen.command(name="transcript", description="Show the most recent transcript lines (if any).")
    @app_commands.guild_only()
    async def transcript(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        rows = [r for r in ctl.transcripts() if r.get("user_id") == interaction.user.id][-10:]
        if not rows:
            await interaction.response.send_message(
                "no transcript yet. transcripts appear once a capture client + transcription engine are "
                "connected — none is configured, so nothing is captured (this is honest, not a bug).",
                ephemeral=True)
            return
        lines = [f"`{r.get('speaker_id','?')}`: {str(r.get('text',''))[:150]}" for r in rows]
        await interaction.response.send_message("📝 recent transcript:\n" + "\n".join(lines), ephemeral=True)

    @listen.command(name="search", description="Search your stored transcripts.")
    @app_commands.describe(query="Text to find.", speaker="Filter by speaker id.", date="YYYY-MM-DD filter.")
    @app_commands.guild_only()
    async def search(self, interaction: discord.Interaction, query: str = "",
                     speaker: str = "", date: str = "") -> None:
        ctl = await _ctl(interaction.guild)
        results = [r for r in ctl.search(query, speaker=speaker, date=date, limit=10)
                   if r.get("user_id") == interaction.user.id]
        if not results:
            await interaction.response.send_message(
                "no matches (or nothing captured yet — see `/listen transcript`).", ephemeral=True)
            return
        lines = [f"• `{r.get('session_id','?')}` {r.get('speaker_id','?')}: "
                 f"\"{str(r.get('text',''))[:120]}\"" for r in results]
        await interaction.response.send_message("🔎 results:\n" + "\n".join(lines), ephemeral=True)

    # ── retention / privacy / delete ──────────────────────────────────────
    @listen.command(name="retention", description="View or set retention (raw audio hours, transcript days).")
    @app_commands.describe(raw_hours="Hours to keep raw audio (0=never, -1=forever).",
                           transcript_days="Days to keep transcripts (-1=forever).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def retention(self, interaction: discord.Interaction,
                        raw_hours: int | None = None, transcript_days: int | None = None) -> None:
        ctl = await _ctl(interaction.guild)
        pol = ctl.policy()
        if raw_hours is not None:
            pol.raw_audio_seconds = raw_hours * 3600 if raw_hours >= 0 else -1
        if transcript_days is not None:
            pol.transcript_seconds = transcript_days * 86400 if transcript_days >= 0 else -1
        if raw_hours is not None or transcript_days is not None:
            await ctl.set_policy(pol)
        def _fmt(sec: int, unit: int, label: str) -> str:
            return "forever" if sec < 0 else "never" if sec == 0 else f"{sec // unit} {label}"
        await interaction.response.send_message(
            f"🗓️ retention — raw audio: **{_fmt(pol.raw_audio_seconds, 3600, 'h')}**, "
            f"transcripts: **{_fmt(pol.transcript_seconds, 86400, 'd')}**.", ephemeral=True)

    @listen.command(name="delete", description="Delete your active/most-recent session's stored data.")
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction) -> None:
        ctl = await _ctl(interaction.guild)
        session = ctl.active_session_for(interaction.user.id)
        if session is None:
            mine = [s for s in (ctl.get_session(sid) for sid in ctl._sessions())  # noqa: SLF001
                    if s and s.user_id == interaction.user.id]
            mine.sort(key=lambda s: -s.created_at)
            session = mine[0] if mine else None
        if session is None:
            await interaction.response.send_message("no session to delete.", ephemeral=True)
            return
        removed = await ctl.delete_session_data(session.id)
        await interaction.response.send_message(
            f"🧹 deleted **{removed}** transcript record(s) for `{session.id}`. an audit event was written "
            f"(without the deleted content).", ephemeral=True)

    @listen.command(name="privacy", description="How this feature handles your data.")
    @app_commands.guild_only()
    async def privacy(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🔐 listen — privacy",
            description=(
                "• capture is **explicitly activated** by you and consent-gated.\n"
                "• the capture client shows a **visible recording indicator** and you can stop locally.\n"
                "• data is **scoped to you**; retention + deletion are configurable (`/listen retention`, `/listen delete`).\n"
                "• every action is **audited** (`/listen history`); deletions record that they happened, not the content.\n"
                "• speaker identity, age, and voice category — if ever enabled — are **estimates**, never asserted facts.\n"
                "• recording other people may require their consent where you live — that's on you to follow."),
            color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @listen.command(name="help", description="What this is, and what's external.")
    @app_commands.guild_only()
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        engines = ENGINES.status()
        eng = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in engines.items())
        embed = discord.Embed(
            title="🎙️ listen — overview",
            description=(
                "an authorized audio-observation platform you control from discord.\n\n"
                "**flow:** `/listen start` → read the notice → `/listen consent` → capture runs → "
                "`/listen stop`. search with `/listen search`, review with `/listen transcript` / "
                "`/listen history`, manage data with `/listen retention` / `/listen delete`.\n\n"
                "**what's external (by design):** the bot can't read your microphone. actual capture "
                "needs a separate **capture client** app, and transcription/diarization/translation need "
                "a probabilistic **engine** plugged in. until those are connected, sessions are authorized "
                "and audited but produce no transcripts — nothing is faked.\n\n"
                f"engines currently: {eng}"),
            color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ListenCog(bot))
