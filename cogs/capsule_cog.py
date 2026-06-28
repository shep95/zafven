"""Time Capsule — write a message now; zafven delivers it on a future date."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import store, dates

log = logging.getLogger("zafven.capsule")

MAX_YEARS = 5


class CapsuleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.deliver.start()

    def cog_unload(self) -> None:
        self.deliver.cancel()

    @app_commands.command(name="capsule", description="Send a message to the future — delivered on a date you pick.")
    @app_commands.describe(
        message="What to say to your future self / the server.",
        deliver_on="Delivery date, e.g. 2027-01-01",
        public="Deliver publicly in this channel (else DM'd to you). Default False.")
    @app_commands.guild_only()
    async def capsule(self, interaction: discord.Interaction, message: str,
                      deliver_on: str, public: bool = False) -> None:
        try:
            day = dates.parse_date(deliver_on)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        deliver_dt = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if deliver_dt <= now:
            await interaction.response.send_message("❌ Pick a future date.", ephemeral=True)
            return
        if (deliver_dt - now).days > MAX_YEARS * 365:
            await interaction.response.send_message(f"❌ Max {MAX_YEARS} years out.", ephemeral=True)
            return

        s = await store.get_store(interaction.guild)
        capsules = list(s.get("capsules", []) or [])
        capsules.append({
            "author_id": interaction.user.id,
            "channel_id": interaction.channel_id,
            "message": message[:1500],
            "deliver_ts": int(deliver_dt.timestamp()),
            "public": public,
        })
        await s.set("capsules", capsules)
        await interaction.response.send_message(
            f"⏳ Sealed. Your capsule opens <t:{int(deliver_dt.timestamp())}:D>"
            + ("" if public else " (delivered to your DMs)."), ephemeral=True)

    @tasks.loop(hours=6)
    async def deliver(self) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for guild in list(self.bot.guilds):
            s = await store.get_store(guild)
            capsules = list(s.get("capsules", []) or [])
            due = [c for c in capsules if c.get("deliver_ts", 0) <= now_ts]
            if not due:
                continue
            for c in due:
                await self._deliver_one(guild, c)
            remaining = [c for c in capsules if c.get("deliver_ts", 0) > now_ts]
            await s.set("capsules", remaining)

    async def _deliver_one(self, guild: discord.Guild, c: dict) -> None:
        member = guild.get_member(c["author_id"])
        embed = discord.Embed(
            title="⏳ A Time Capsule Opens",
            description=c["message"], color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc))
        embed.set_footer(text="Sealed in the past, delivered today.")
        try:
            if c.get("public"):
                channel = guild.get_channel(c.get("channel_id")) or guild.system_channel
                if channel:
                    mention = member.mention if member else ""
                    await channel.send(content=mention, embed=embed)
            elif member:
                await member.send(embed=embed)
        except discord.HTTPException as exc:
            log.warning("Capsule delivery failed: %s", exc)

    @deliver.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CapsuleCog(bot))
