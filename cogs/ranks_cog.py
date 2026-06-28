"""Initiation Ranks — earn XP by chatting; cross thresholds to earn roles.

XP is held in memory and flushed to the Discord-backed store every few minutes.
Level = floor(sqrt(xp / 100)). The role ladder is configurable (RANK_LADDER).
"""
from __future__ import annotations

import logging
import math
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import store

log = logging.getLogger("zafven.ranks")


def level_for_xp(xp: int) -> int:
    return int(math.sqrt(max(xp, 0) / 100))


def _parse_ladder() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for item in config.RANK_LADDER:
        if ":" in item:
            name, lvl = item.rsplit(":", 1)
            try:
                out.append((int(lvl), name.strip()))
            except ValueError:
                continue
    return sorted(out)


class RanksCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ladder = _parse_ladder()
        self._xp: dict[int, dict[int, int]] = {}
        self._loaded: set[int] = set()
        self._dirty: set[int] = set()
        self._cooldown: dict[tuple[int, int], float] = {}
        self.flush.start()

    def cog_unload(self) -> None:
        self.flush.cancel()

    async def _ensure_loaded(self, guild: discord.Guild) -> None:
        if guild.id in self._loaded:
            return
        s = await store.get_store(guild)
        data = s.get("xp", {}) or {}
        self._xp[guild.id] = {int(k): int(v) for k, v in data.items()}
        self._loaded.add(guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.RANKS_ENABLED or message.author.bot or message.guild is None:
            return
        key = (message.guild.id, message.author.id)
        now = time.time()
        if now - self._cooldown.get(key, 0) < config.RANK_COOLDOWN_SECONDS:
            return
        self._cooldown[key] = now

        await self._ensure_loaded(message.guild)
        table = self._xp[message.guild.id]
        before = table.get(message.author.id, 0)
        after = before + random.randint(5, 15)
        table[message.author.id] = after
        self._dirty.add(message.guild.id)

        if level_for_xp(after) > level_for_xp(before):
            await self._on_level_up(message, level_for_xp(after))

    async def _on_level_up(self, message: discord.Message, level: int) -> None:
        member = message.author
        assert isinstance(member, discord.Member)
        role_name = self._role_for_level(level)
        if role_name and message.guild.me.guild_permissions.manage_roles:
            role = discord.utils.get(message.guild.roles, name=role_name)
            try:
                if role is None:
                    role = await message.guild.create_role(name=role_name, reason="zafven rank")
                if role < message.guild.me.top_role and role not in member.roles:
                    await member.add_roles(role, reason=f"Reached level {level}")
            except discord.HTTPException as exc:
                log.warning("Role grant failed: %s", exc)
        try:
            tag = f" — **{role_name}**" if role_name else ""
            await message.channel.send(f"✨ {member.mention} reached **level {level}**{tag}!")
        except discord.HTTPException:
            pass

    def _role_for_level(self, level: int) -> str | None:
        name = None
        for lvl, role in self.ladder:
            if level >= lvl:
                name = role
        return name

    @tasks.loop(minutes=5)
    async def flush(self) -> None:
        for gid in list(self._dirty):
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            s = await store.get_store(guild)
            await s.set("xp", {str(k): v for k, v in self._xp.get(gid, {}).items()})
            self._dirty.discard(gid)

    @flush.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="rank", description="Show your (or someone's) initiation rank.")
    @app_commands.describe(member="Whose rank to show (default: you).")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user  # type: ignore[assignment]
        await self._ensure_loaded(interaction.guild)
        xp = self._xp[interaction.guild.id].get(member.id, 0)
        level = level_for_xp(xp)
        nxt = (level + 1) ** 2 * 100
        embed = discord.Embed(title=f"🔮 {member.display_name}'s Rank", color=discord.Color.purple())
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="XP", value=f"{xp} / {nxt}")
        embed.add_field(name="Title", value=self._role_for_level(level) or "—")
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Top members by XP.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await self._ensure_loaded(interaction.guild)
        table = self._xp[interaction.guild.id]
        top = sorted(table.items(), key=lambda kv: kv[1], reverse=True)[:10]
        if not top:
            await interaction.response.send_message("No XP yet — start chatting!", ephemeral=True)
            return
        lines = []
        for i, (uid, xp) in enumerate(top, 1):
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            lines.append(f"**{i}.** {name} — level {level_for_xp(xp)} ({xp} XP)")
        embed = discord.Embed(title="🏆 Initiation Leaderboard", description="\n".join(lines),
                              color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RanksCog(bot))
