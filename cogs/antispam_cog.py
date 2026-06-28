"""Anti-spam / anti-scam: flood, duplicates, mass-mentions, invite & scam links.

Heuristic and self-contained (no external calls). When a message trips a rule the
bot deletes it, optionally times the member out, and posts a short auto-deleting
warning. Needs Manage Messages (to delete) and Moderate Members (to timeout).
"""
from __future__ import annotations

import collections
import logging
import re
from datetime import timedelta

import discord
from discord.ext import commands

import config

log = logging.getLogger("zafven.antispam")

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)\S+", re.IGNORECASE)
SCAM_RE = re.compile(
    r"(free\s+nitro|nitro\s+(?:giveaway|gift)|steamcommunity\.com/gift|"
    r"claim\s+your\s+(?:free|reward)|free\s+\$?\d+\s*(?:gift|steam))",
    re.IGNORECASE,
)


class AntiSpamCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # (guild_id, user_id) -> deque of (timestamp, content)
        self._recent: dict[tuple[int, int], collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=15))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.ANTISPAM_ENABLED:
            return
        if message.author.bot or message.guild is None:
            return
        member = message.author
        if config.ANTISPAM_BYPASS_MODS and isinstance(member, discord.Member):
            if member.guild_permissions.manage_messages:
                return

        reasons = self._scan(message)
        if not reasons:
            return

        await self._act(message, reasons)

    def _scan(self, message: discord.Message) -> list[str]:
        key = (message.guild.id, message.author.id)
        dq = self._recent[key]
        now = message.created_at.timestamp()
        dq.append((now, message.content))
        reasons: list[str] = []

        recent_window = [t for t, _ in dq if now - t <= config.ANTISPAM_FLOOD_SECONDS]
        if len(recent_window) >= config.ANTISPAM_FLOOD_COUNT:
            reasons.append("flooding")

        if message.content.strip():
            same = sum(1 for _, c in dq if c == message.content)
            if same >= config.ANTISPAM_DUPLICATE_COUNT:
                reasons.append("repeated messages")

        if len(message.mentions) + len(message.role_mentions) > config.ANTISPAM_MAX_MENTIONS:
            reasons.append("mass mentions")

        if config.ANTISPAM_BLOCK_INVITES and INVITE_RE.search(message.content):
            reasons.append("invite link")
        if SCAM_RE.search(message.content):
            reasons.append("scam link")

        return reasons

    async def _act(self, message: discord.Message, reasons: list[str]) -> None:
        guild = message.guild
        me = guild.me
        if message.channel.permissions_for(me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        timed_out = False
        if (config.ANTISPAM_TIMEOUT_SECONDS > 0 and isinstance(message.author, discord.Member)
                and me.guild_permissions.moderate_members
                and message.author.top_role < me.top_role
                and message.author.id != guild.owner_id):
            try:
                await message.author.timeout(
                    timedelta(seconds=config.ANTISPAM_TIMEOUT_SECONDS),
                    reason=f"zafven anti-spam: {', '.join(reasons)}")
                timed_out = True
            except discord.HTTPException:
                pass

        try:
            mute = " You've been muted briefly." if timed_out else ""
            warn = await message.channel.send(
                f"🛡️ {message.author.mention}, that looked like **{reasons[0]}**.{mute}")
            await warn.delete(delay=6)
        except discord.HTTPException:
            pass
        log.info("Anti-spam acted on %s in %s: %s", message.author, guild.name, reasons)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiSpamCog(bot))
