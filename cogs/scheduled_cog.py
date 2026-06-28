"""Scheduled broadcasts: a daily transit reading + koan, and a weekly egregore digest.

Fires once a day at DAILY_HOUR_UTC. The weekly digest runs on Mondays and is
strictly aggregate — it describes the room's themes, never individuals.
"""
from __future__ import annotations

import datetime as dt
import logging

import discord
from discord.ext import commands, tasks

import config
from core.brain_loader import load as load_brain, persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.scheduled")


class ScheduledCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.daily.change_interval(time=dt.time(hour=config.DAILY_HOUR_UTC, tzinfo=dt.timezone.utc))
        if config.DAILY_ENABLED:
            self.daily.start()

    def cog_unload(self) -> None:
        self.daily.cancel()

    @tasks.loop(time=dt.time(hour=13, tzinfo=dt.timezone.utc))
    async def daily(self) -> None:
        for guild in list(self.bot.guilds):
            channel = discord.utils.get(guild.text_channels, name=config.DAILY_CHANNEL)
            if not channel or not channel.permissions_for(guild.me).send_messages:
                continue
            await self._post_daily(channel)
            if dt.datetime.now(dt.timezone.utc).weekday() == 0:  # Monday
                await self._post_egregore(guild, channel)

    async def _post_daily(self, channel: discord.TextChannel) -> None:
        prompt = (
            "Give today's collective transit reading: use web search for today's real major "
            "planetary transits, then a short symbolic 'energy of the day' for everyone. End with "
            "a single original koan (one line). Entertainment only — no financial/medical/forecast claims."
        )
        try:
            text = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("prediction"), prompt, web_search=True, max_tokens=900)
        except GatewayError as exc:
            log.warning("daily broadcast failed: %s", exc)
            return
        embed = discord.Embed(title="🌅 Today's Transit", description=text[:4000],
                              color=discord.Color.dark_gold(),
                              timestamp=dt.datetime.now(dt.timezone.utc))
        embed.set_footer(text="zafven • daily broadcast • for reflection")
        await channel.send(embed=embed)

    async def _post_egregore(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        snippets: list[str] = []
        for ch in guild.text_channels:
            if len(snippets) >= 150 or not ch.permissions_for(guild.me).read_message_history:
                continue
            try:
                async for msg in ch.history(limit=40):
                    if msg.author.bot or not msg.content.strip():
                        continue
                    snippets.append(msg.content)
                    if len(snippets) >= 150:
                        break
            except discord.HTTPException:
                continue
        if len(snippets) < 15:
            return
        corpus = "\n".join(snippets)[:40000]
        system = (f"{load_brain('persona')}\n\nSummarize ONLY the aggregate themes and mood of a "
                  "community's week. Never name, quote, or single out any individual. Themes, not people.")
        try:
            text = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                system, f"What has the server collectively been focused on?\n\n{corpus}",
                web_search=False, max_tokens=700)
        except GatewayError as exc:
            log.warning("egregore failed: %s", exc)
            return
        embed = discord.Embed(title="🌐 Weekly Egregore", description=text[:4000],
                              color=discord.Color.dark_teal())
        embed.set_footer(text="zafven • aggregate themes only")
        await channel.send(embed=embed)

    @daily.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ScheduledCog(bot))
