"""Welcome DMs + invite tracking + referral leaderboard.

- New members get a personal welcome DM with their own shareable invite link.
- The bot tracks which invite each new member used (uses-diff method) and credits
  the inviter, so a monthly "most invites" contest has a real leaderboard.
- `/invite` hands anyone their personal, tracked, never-expiring invite link.
- `/invites` and `/invitelb` show counts and the leaderboard.

Needs the **Manage Server** permission (to read invites for attribution) and
**Create Invite** (to mint links). Without Manage Server the welcome DM still
works, but attribution can't be computed.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import invites

log = logging.getLogger("zafven.invites")


class InvitesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> {invite_code: uses} snapshot for the uses-diff attribution
        self._cache: dict[int, dict[str, int]] = {}
        self._primed = False

    # ── invite cache (for attribution) ───────────────────────────────────
    async def _snapshot(self, guild: discord.Guild) -> dict[str, int]:
        try:
            return {i.code: (i.uses or 0) for i in await guild.invites()}
        except (discord.Forbidden, discord.HTTPException):
            return {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._primed:
            return
        self._primed = True
        for guild in self.bot.guilds:
            self._cache[guild.id] = await self._snapshot(guild)

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild) -> None:
        self._cache[guild.id] = await self._snapshot(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            self._cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            self._cache.get(invite.guild.id, {}).pop(invite.code, None)

    # ── helpers ──────────────────────────────────────────────────────────
    async def _invite_channel(self, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        me = guild.me
        if guild.system_channel and guild.system_channel.permissions_for(me).create_instant_invite:
            return guild.system_channel
        for ch in guild.text_channels:
            if ch.permissions_for(me).create_instant_invite:
                return ch
        for ch in guild.voice_channels:
            if ch.permissions_for(me).create_instant_invite:
                return ch
        return None

    async def _personal_invite(self, guild: discord.Guild, member: discord.abc.User) -> str | None:
        """Return a stable, tracked, never-expiring invite URL owned by `member`."""
        code = await invites.get_personal(guild, member.id)
        if code:
            for inv in await self._safe_invites(guild):
                if inv.code == code:
                    return inv.url
        channel = await self._invite_channel(guild)
        if channel is None:
            return None
        try:
            inv = await channel.create_invite(
                max_age=0, max_uses=0, unique=True,
                reason=f"personal invite for {member} (referral tracking)")
        except discord.HTTPException as exc:
            log.warning("could not create personal invite: %s", exc)
            return None
        await invites.set_personal(guild, member.id, inv.code)
        self._cache.setdefault(guild.id, {})[inv.code] = 0
        return inv.url

    async def _safe_invites(self, guild: discord.Guild) -> list[discord.Invite]:
        try:
            return await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return []

    def _welcome_text(self, member: discord.abc.User, link: str | None) -> str:
        base = config.WELCOME_DM_MESSAGE or _DEFAULT_WELCOME
        if link:
            base += f"\n\nyour personal invite link: {link}"
        return base

    # ── member join: welcome DM + attribution ────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not config.INVITES_ENABLED or member.bot:
            # keep the cache fresh even for bot joins
            self._cache[member.guild.id] = await self._snapshot(member.guild)
            return
        guild = member.guild

        # 1) figure out who invited them (before refreshing the cache)
        inviter = await self._attribute(guild, member)

        # 2) welcome DM with their own shareable link
        if config.WELCOME_DM_ENABLED:
            try:
                link = await self._personal_invite(guild, member)
                await member.send(self._welcome_text(member, link))
            except discord.HTTPException:
                pass  # DMs closed, etc. — never block on this

        # 3) credit + announce
        if inviter is not None:
            try:
                total = await invites.add_credit(guild, inviter.id, 1)
                await self._announce(guild, member, inviter, total)
            except Exception:  # noqa: BLE001
                log.exception("invite credit failed")

    async def _attribute(self, guild: discord.Guild, member: discord.Member) -> discord.abc.User | None:
        before = self._cache.get(guild.id, {})
        current = await self._safe_invites(guild)
        after: dict[str, int] = {}
        used: discord.Invite | None = None
        for inv in current:
            after[inv.code] = inv.uses or 0
            if (inv.uses or 0) > before.get(inv.code, 0) and used is None:
                used = inv
        self._cache[guild.id] = after
        if used and used.inviter and not used.inviter.bot and used.inviter.id != member.id:
            return used.inviter
        return None

    async def _announce(self, guild: discord.Guild, member: discord.Member,
                        inviter: discord.abc.User, total: int) -> None:
        name = config.INVITE_LOG_CHANNEL.strip()
        if not name:
            return
        channel = discord.utils.get(guild.text_channels, name=name)
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            return
        try:
            await channel.send(
                f"🎉 {member.mention} joined — invited by {inviter.mention}, now at **{total}** invite(s).")
        except discord.HTTPException:
            pass

    # ── commands ─────────────────────────────────────────────────────────
    @app_commands.command(name="invite", description="Get your personal, trackable invite link.")
    @app_commands.guild_only()
    async def invite(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        link = await self._personal_invite(interaction.guild, interaction.user)
        if not link:
            await interaction.followup.send(
                "❌ I couldn't make an invite — I need the **Create Invite** permission in a channel.",
                ephemeral=True)
            return
        count = await invites.get_count(interaction.guild, interaction.user.id)
        await interaction.followup.send(
            f"🔗 here's your personal invite link — share it to climb the leaderboard:\n{link}\n"
            f"you've brought in **{count}** member(s) so far.", ephemeral=True)

    @app_commands.command(name="invites", description="See how many members someone has invited.")
    @app_commands.describe(member="Whose invite count to check (default: you).")
    @app_commands.guild_only()
    async def invites_cmd(self, interaction: discord.Interaction,
                          member: discord.Member | None = None) -> None:
        member = member or interaction.user  # type: ignore[assignment]
        count = await invites.get_count(interaction.guild, member.id)
        await interaction.response.send_message(
            f"📨 {member.mention} has invited **{count}** member(s).", ephemeral=True)

    @app_commands.command(name="invitelb", description="Top inviters — the monthly Nitro leaderboard.")
    @app_commands.guild_only()
    async def invitelb(self, interaction: discord.Interaction) -> None:
        top = await invites.leaderboard(interaction.guild, limit=10)
        if not top:
            await interaction.response.send_message(
                "no invites tracked yet — grab your link with `/invite` and start sharing!")
            return
        lines = []
        for i, (uid, count) in enumerate(top, 1):
            m = interaction.guild.get_member(uid)
            name = m.mention if m else f"`user {uid}`"
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"**{i}.**")
            lines.append(f"{medal} {name} — **{count}** invite(s)")
        embed = discord.Embed(
            title="🏆 invite leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold())
        embed.set_footer(text="most invites this month wins nitro from asher himself")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="announcewelcome",
                          description="DM the welcome message to every current member (admins only).")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def announcewelcome(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        members = [m for m in guild.members if not m.bot]
        sent = failed = 0
        for m in members:
            try:
                link = await self._personal_invite(guild, m)
                await m.send(self._welcome_text(m, link))
                sent += 1
            except discord.HTTPException:
                failed += 1
            await asyncio.sleep(1.0)  # be gentle — Discord rate-limits DMs hard
        await interaction.followup.send(
            f"📣 welcome DM sent to **{sent}** members ({failed} had DMs closed).", ephemeral=True)


_DEFAULT_WELCOME = (
    "welcome to the **#houseofasher** community and digital empire — we're so glad you're here. 🖤\n\n"
    "if you'd like to help us grow, share your personal invite link with people. "
    "each month, whoever's invite link brings in the most new members wins **nitro from asher himself**."
)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InvitesCog(bot))
