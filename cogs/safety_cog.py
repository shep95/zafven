"""Personal safety companion (`/safety`).

For "walking somewhere sketchy": start a timed check-in; if you don't mark yourself
safe before it runs out, the bot DMs the trusted contacts you chose. `/safety sos`
alerts them immediately. It records NOBODY and profiles NOBODY — it's a dead-man's
switch built on consent, which is the legal, genuinely-useful core of a safety tool.

Timers survive restarts: active check-ins are persisted and re-armed on ready (a
check-in already overdue after downtime fires its alert immediately).
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import safety, store as store_mod

log = logging.getLogger("zafven.safety")


class SafetyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tasks: dict[tuple[int, int], asyncio.Task] = {}  # (guild,user) -> timer task

    # ── re-arm persisted check-ins after a restart ───────────────────────
    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not config.SAFETY_ENABLED:
            return
        for guild in self.bot.guilds:
            try:
                s = await store_mod.get_store(guild)
            except Exception:  # noqa: BLE001
                continue
            for uid_str, entry in safety.all_checkins(s).items():
                try:
                    self._arm(guild.id, int(uid_str), entry)
                except Exception:  # noqa: BLE001
                    log.exception("re-arm check-in failed")

    def cog_unload(self) -> None:
        for task in self._tasks.values():
            task.cancel()

    def _arm(self, guild_id: int, user_id: int, entry: dict) -> None:
        key = (guild_id, user_id)
        old = self._tasks.pop(key, None)
        if old:
            old.cancel()
        delay = max(0, safety.remaining_seconds(entry))
        self._tasks[key] = self.bot.loop.create_task(self._fire_after(guild_id, user_id, delay))

    async def _fire_after(self, guild_id: int, user_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return
            s = await store_mod.get_store(guild)
            entry = safety.get_checkin(s, user_id)
            if entry is None:            # marked safe / cancelled while we slept
                return
            await self._alert_contacts(guild, user_id, kind="overdue",
                                       note=entry.get("note", ""), minutes=entry.get("minutes", 0))
            await safety.clear_checkin(s, user_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("check-in fire failed")
        finally:
            self._tasks.pop((guild_id, user_id), None)

    async def _alert_contacts(self, guild: discord.Guild, user_id: int, *, kind: str,
                              note: str = "", minutes: int = 0) -> int:
        s = await store_mod.get_store(guild)
        contacts = safety.get_contacts(s, user_id)
        member = guild.get_member(user_id)
        name = member.display_name if member else f"user {user_id}"
        profile = safety.get_profile(s, user_id).get("note", "")
        text = safety.alert_text(name, kind=kind, note=note, minutes=minutes, profile_note=profile)
        sent = 0
        for cid in contacts:
            user = self.bot.get_user(cid) or await self._fetch_user(cid)
            if user is None:
                continue
            try:
                await user.send(text)
                sent += 1
            except discord.HTTPException:
                pass
        # optional: also post to a safety channel if configured
        chan_name = config.SAFETY_ALERT_CHANNEL.strip()
        if chan_name:
            ch = discord.utils.get(guild.text_channels, name=chan_name)
            if ch and ch.permissions_for(guild.me).send_messages:
                try:
                    await ch.send(text)
                except discord.HTTPException:
                    pass
        return sent

    async def _fetch_user(self, user_id: int) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    # ── command group ─────────────────────────────────────────────────────
    safety_grp = app_commands.Group(name="safety", description="Personal safety check-ins and SOS (no recording).")

    @safety_grp.command(name="checkin", description="Start a timed check-in; if you don't mark safe, contacts are alerted.")
    @app_commands.describe(minutes="Minutes until the alert fires (1–1440).", note="Optional note for your contacts (e.g. where you're going).")
    @app_commands.guild_only()
    async def checkin(self, interaction: discord.Interaction, minutes: int, note: str = "") -> None:
        if not config.SAFETY_ENABLED:
            await interaction.response.send_message("the safety feature is off.", ephemeral=True)
            return
        s = await store_mod.get_store(interaction.guild)
        if not safety.get_contacts(s, interaction.user.id):
            await interaction.response.send_message(
                "add at least one trusted contact first with `/safety contact add @someone` — "
                "they're who i'll alert if you don't check in.", ephemeral=True)
            return
        entry = await safety.start_checkin(s, interaction.user.id, minutes, note, interaction.channel_id or 0)
        self._arm(interaction.guild.id, interaction.user.id, entry)
        await interaction.response.send_message(
            f"⏱️ check-in started for **{entry['minutes']} min**. mark yourself safe with `/safety ok` "
            f"before then, or i'll alert your contacts. stay safe. 🖤", ephemeral=True)

    @safety_grp.command(name="ok", description="Mark yourself safe and cancel the active check-in.")
    @app_commands.guild_only()
    async def ok(self, interaction: discord.Interaction) -> None:
        s = await store_mod.get_store(interaction.guild)
        cleared = await safety.clear_checkin(s, interaction.user.id)
        key = (interaction.guild.id, interaction.user.id)
        task = self._tasks.pop(key, None)
        if task:
            task.cancel()
        msg = "✅ glad you're safe — check-in cancelled." if cleared else "you don't have an active check-in."
        await interaction.response.send_message(msg, ephemeral=True)

    @safety_grp.command(name="sos", description="Alert your trusted contacts right now.")
    @app_commands.describe(message="Optional message to include.")
    @app_commands.guild_only()
    async def sos(self, interaction: discord.Interaction, message: str = "") -> None:
        if not config.SAFETY_ENABLED:
            await interaction.response.send_message("the safety feature is off.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        s = await store_mod.get_store(interaction.guild)
        if not safety.get_contacts(s, interaction.user.id):
            await interaction.followup.send(
                "you have no contacts to alert — add one with `/safety contact add @someone`.", ephemeral=True)
            return
        sent = await self._alert_contacts(interaction.guild, interaction.user.id, kind="sos", note=message)
        await interaction.followup.send(
            f"🚨 SOS sent to **{sent}** contact(s). if you're in danger, call local emergency services now.",
            ephemeral=True)

    @safety_grp.command(name="status", description="Show your active check-in and contacts.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        s = await store_mod.get_store(interaction.guild)
        entry = safety.get_checkin(s, interaction.user.id)
        contacts = safety.get_contacts(s, interaction.user.id)
        names = ", ".join((interaction.guild.get_member(c).mention if interaction.guild.get_member(c)
                           else f"`{c}`") for c in contacts) or "_(none yet)_"
        if entry:
            mins = max(0, safety.remaining_seconds(entry)) // 60
            state = f"active — **~{mins} min** left. mark safe with `/safety ok`."
        else:
            state = "no active check-in."
        await interaction.response.send_message(
            f"🛡️ **safety status**\ncheck-in: {state}\ntrusted contacts: {names}", ephemeral=True)

    # contacts sub-group
    contact = app_commands.Group(name="contact", description="Manage your trusted safety contacts.", parent=safety_grp)

    @contact.command(name="add", description="Add a trusted contact who gets alerted if you don't check in.")
    @app_commands.describe(user="The person to add (ask them first — they'll get your alerts).")
    @app_commands.guild_only()
    async def contact_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if user.bot:
            await interaction.response.send_message("that's a bot — pick a real person.", ephemeral=True)
            return
        s = await store_mod.get_store(interaction.guild)
        ok, why = await safety.add_contact(s, interaction.user.id, user.id)
        if ok:
            await interaction.response.send_message(
                f"added {user.mention} as a trusted contact. please make sure they've agreed — "
                f"they'll receive a DM if you miss a check-in or send an SOS.", ephemeral=True)
        else:
            await interaction.response.send_message(why, ephemeral=True)

    @contact.command(name="remove", description="Remove a trusted contact.")
    @app_commands.guild_only()
    async def contact_remove(self, interaction: discord.Interaction, user: discord.Member) -> None:
        s = await store_mod.get_store(interaction.guild)
        removed = await safety.remove_contact(s, interaction.user.id, user.id)
        msg = f"removed {user.mention}." if removed else "they weren't on your list."
        await interaction.response.send_message(msg, ephemeral=True)

    @contact.command(name="list", description="List your trusted contacts.")
    @app_commands.guild_only()
    async def contact_list(self, interaction: discord.Interaction) -> None:
        s = await store_mod.get_store(interaction.guild)
        contacts = safety.get_contacts(s, interaction.user.id)
        if not contacts:
            await interaction.response.send_message(
                "no contacts yet — add one with `/safety contact add @someone`.", ephemeral=True)
            return
        names = "\n".join(f"• {(interaction.guild.get_member(c).mention if interaction.guild.get_member(c) else f'`{c}`')}"
                          for c in contacts)
        await interaction.response.send_message(f"🫂 your trusted contacts:\n{names}", ephemeral=True)

    @safety_grp.command(name="help", description="How the safety feature works (and what it does NOT do).")
    @app_commands.guild_only()
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🛡️ safety companion",
            description=(
                "a check-in safety net for when you're heading somewhere and want someone to know "
                "if something goes wrong.\n\n"
                "**how it works**\n"
                "1. `/safety contact add @someone` — pick trusted people (ask them first).\n"
                "2. `/safety checkin 30 heading home from the station` — start a timer.\n"
                "3. mark safe with `/safety ok` before it runs out.\n"
                "4. if you don't, i DM your contacts so they can check on you.\n"
                "`/safety sos` alerts them immediately.\n\n"
                "**what it does NOT do**\n"
                "it does not record audio, listen to you, or track anyone. it's just a timed "
                "alert to people you chose. in a real emergency, always call local emergency services."),
            color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SafetyCog(bot))
