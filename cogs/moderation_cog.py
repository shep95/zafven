"""Inactivity cleanup: preview, confirm, kick, and send a friendly reinvite DM."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import activity

log = logging.getLogger("zafven.moderation")

PER_MEMBER_DELAY = 1.2


def _fmt_last_active(when: datetime | None) -> str:
    return "never seen (in scan window)" if when is None else f"<t:{int(when.timestamp())}:R>"


async def _invite_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).create_instant_invite:
        return guild.system_channel
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).create_instant_invite:
            return ch
    return None


async def _make_reinvite(guild: discord.Guild) -> str | None:
    channel = await _invite_channel(guild)
    if not channel:
        return None
    try:
        invite = await channel.create_invite(max_age=0, max_uses=1, unique=True,
                                             reason="zafven reinvite for inactive member")
        return invite.url
    except discord.HTTPException as exc:
        log.warning("Invite creation failed: %s", exc)
        return None


class ConfirmKick(discord.ui.View):
    def __init__(self, author_id: int, members: list[discord.Member]) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.members = members
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command runner can confirm.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Kick them", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="⏳ Working…", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled. Nobody was kicked.", view=self)
        self.stop()


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="kick_inactive",
        description="Preview or kick members with no messages in the last N days (sends a reinvite DM).")
    @app_commands.describe(
        days="Inactivity threshold in days (default from config).",
        dry_run="Preview only — show who WOULD be kicked. Default True.",
        message="Custom reinvite DM message (optional).")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick_inactive(self, interaction: discord.Interaction, days: int | None = None,
                            dry_run: bool = True, message: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if not guild.me.guild_permissions.kick_members:
            await interaction.response.send_message("I lack the **Kick Members** permission.", ephemeral=True)
            return
        days = days or config.DEFAULT_INACTIVE_DAYS
        if days < 1:
            await interaction.response.send_message("`days` must be at least 1.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        inactive = await activity.find_inactive(
            guild=guild, inactive_days=days, scan_limit=config.ACTIVITY_SCAN_LIMIT,
            protected_roles=config.PROTECTED_ROLES, join_grace_days=config.JOIN_GRACE_DAYS)

        if not inactive:
            await interaction.followup.send(f"✅ No members inactive past **{days} days**. Nothing to do.")
            return

        preview = self._preview_embed(inactive, days, dry_run)
        if dry_run:
            preview.set_footer(text="Dry run — nobody was kicked. Re-run with dry_run:False to act.")
            await interaction.followup.send(embed=preview)
            return

        members = [im.member for im in inactive]
        view = ConfirmKick(interaction.user.id, members)
        await interaction.followup.send(
            content=f"⚠️ This will **kick {len(members)} members** and DM each a reinvite. Confirm?",
            embed=preview, view=view)
        await view.wait()
        if not view.confirmed:
            return
        await self._execute_kicks(interaction, guild, members, days, message)

    def _preview_embed(self, inactive: list[activity.InactiveMember], days: int, dry_run: bool) -> discord.Embed:
        lines = [f"• {im.member.mention} — last active {_fmt_last_active(im.last_active)}" for im in inactive[:25]]
        if len(inactive) > 25:
            lines.append(f"…and **{len(inactive) - 25}** more")
        embed = discord.Embed(
            title=f"{'🔍 Inactive preview' if dry_run else '⚠️ Pending kicks'} — {len(inactive)} members",
            description="\n".join(lines), color=discord.Color.orange())
        embed.add_field(name="Threshold", value=f"{days} days")
        embed.add_field(name="Scanned", value=f"{config.ACTIVITY_SCAN_LIMIT} msgs/channel")
        embed.add_field(name="Protected roles", value=", ".join(config.PROTECTED_ROLES) or "none")
        return embed

    async def _execute_kicks(self, interaction: discord.Interaction, guild: discord.Guild,
                             members: list[discord.Member], days: int, custom_message: str | None) -> None:
        kicked = dm_ok = dm_failed = 0
        kick_failed: list[str] = []
        me = guild.me
        for member in members:
            if member.top_role >= me.top_role:
                kick_failed.append(f"{member} (role too high)")
                continue
            invite = await _make_reinvite(guild)
            dm_text = custom_message or (
                f"Hey! Sorry, we had to remove you from **{guild.name}** because you'd been inactive "
                f"for over {days} days and we're tidying up the member list. No hard feelings — "
                f"you're welcome back any time. 💚")
            if invite:
                dm_text += f"\n\nRejoin here whenever you like: {invite}"
            try:
                await member.send(dm_text)
                dm_ok += 1
            except discord.HTTPException:
                dm_failed += 1
            try:
                await member.kick(reason=f"zafven inactivity cleanup (>{days}d)")
                kicked += 1
            except discord.HTTPException as exc:
                kick_failed.append(f"{member} ({getattr(exc, 'text', 'error')})")
            await asyncio.sleep(PER_MEMBER_DELAY)

        result = discord.Embed(title="✅ Inactivity cleanup complete", color=discord.Color.green(),
                               timestamp=datetime.now(timezone.utc))
        result.add_field(name="Kicked", value=str(kicked))
        result.add_field(name="Reinvite DMs sent", value=str(dm_ok))
        result.add_field(name="DMs that failed", value=str(dm_failed))
        if kick_failed:
            extra = f"\n…+{len(kick_failed) - 10} more" if len(kick_failed) > 10 else ""
            result.add_field(name="Could not kick", value="\n".join(kick_failed[:10]) + extra, inline=False)
        await interaction.followup.send(embed=result)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
