"""Calls out manipulation / scam *tactics* to protect targets (not character judgments).

When a message matches a known social-engineering pattern (phishing, fake account
verification, giveaway bait, money-doubler, staff impersonation) the bot removes
it, posts a short public **safety notice about the tactic**, and privately alerts
mods with the details. It flags the behaviour, never labels the person. Real
staff (Manage Messages) are exempt, so it won't misfire on your admins.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config
from core import manipulation

log = logging.getLogger("zafven.antimanip")

_ADVICE = {
    "credential phishing": "Never share passwords, 2FA, or recovery codes — no real staff will ask.",
    "fake account-verification": "Don't click 'verify your account' links from DMs or random messages.",
    "giveaway / free-gift bait": "'Free nitro/gift' links are scams — don't click or log in.",
    "money-doubler scam": "No one can double your money — that's always a scam.",
    "staff impersonation": "Real staff won't DM you to 'fix' your account. Verify in public channels.",
}


class AntiManipCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.ANTIMANIP_ENABLED or message.author.bot or message.guild is None:
            return
        if not message.content.strip():
            return
        if config.ANTIMANIP_BYPASS_MODS and isinstance(message.author, discord.Member) \
                and message.author.guild_permissions.manage_messages:
            return

        tactic = manipulation.detect(message.content)
        if not tactic:
            return

        original = message.content
        if message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        # Public safety notice — about the tactic, to protect would-be targets.
        try:
            await message.channel.send(
                f"⚠️ **Safety notice:** a message here matched a known **{tactic}** pattern and was "
                f"removed. {_ADVICE.get(tactic, 'Stay cautious.')} Mods have been alerted.")
        except discord.HTTPException:
            pass

        await self._alert_mods(message, tactic, original)
        log.info("Anti-manipulation flagged %s in %s: %s", message.author, message.guild.name, tactic)

    async def _alert_mods(self, message: discord.Message, tactic: str, content: str) -> None:
        guild = message.guild
        channel = discord.utils.get(guild.text_channels, name=config.MOD_ALERT_CHANNEL)
        if channel is None and guild.me.guild_permissions.manage_channels:
            try:
                overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                              guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
                channel = await guild.create_text_channel(
                    config.MOD_ALERT_CHANNEL, overwrites=overwrites, reason="zafven mod alerts")
            except discord.HTTPException:
                channel = None
        if channel is None:
            return
        embed = discord.Embed(
            title="🚩 Possible scam/manipulation",
            description=f"Tactic: **{tactic}**", color=discord.Color.dark_orange(),
            timestamp=datetime.now(timezone.utc))
        embed.add_field(name="From", value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Channel", value=message.channel.mention)
        embed.add_field(name="Message", value=content[:1024], inline=False)
        embed.set_footer(text="Flagged the behaviour, not the person — review and decide.")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiManipCog(bot))
