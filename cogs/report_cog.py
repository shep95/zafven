"""/report — let members escalate a suspicious message to moderators.

Keeps a human in the loop: the bot doesn't render a verdict, it just forwards the
reported message (with the reporter's reason) to #mod-alerts and pings the mods.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core import modalert

log = logging.getLogger("zafven.report")

LINK_RE = re.compile(r"channels/(\d+)/(\d+)/(\d+)")


class ReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="report", description="Report a message to the moderators.")
    @app_commands.describe(
        message_link="Right-click the message → Copy Message Link, and paste it here.",
        reason="What's wrong with it (optional).")
    @app_commands.guild_only()
    async def report(self, interaction: discord.Interaction, message_link: str,
                     reason: str | None = None) -> None:
        m = LINK_RE.search(message_link)
        if not m:
            await interaction.response.send_message(
                "❌ That's not a valid message link. Right-click a message → **Copy Message Link**.",
                ephemeral=True)
            return
        gid, cid, mid = (int(x) for x in m.groups())
        if gid != interaction.guild.id:
            await interaction.response.send_message("❌ That message isn't from this server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        reported = None
        channel = interaction.guild.get_channel(cid)
        if isinstance(channel, discord.abc.Messageable):
            try:
                reported = await channel.fetch_message(mid)
            except discord.HTTPException:
                reported = None

        alert = await modalert.get_alert_channel(interaction.guild)
        if alert is None:
            await interaction.followup.send(
                "⚠️ I couldn't reach a mod-alerts channel. Ask an admin to create one or give me "
                "Manage Channels.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📣 Member Report", color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Reported by", value=interaction.user.mention)
        embed.add_field(name="Link", value=f"[jump]({message_link})")
        if reported is not None:
            embed.add_field(name="Message author",
                            value=f"{reported.author.mention} (`{reported.author.id}`)", inline=False)
            content = reported.content or "*(no text — attachment/embed)*"
            if reported.attachments:
                content += "\n📎 " + ", ".join(a.filename for a in reported.attachments)
            embed.add_field(name="Content", value=content[:1024], inline=False)
        else:
            embed.add_field(name="Note", value="Couldn't fetch the message (deleted or no access).",
                            inline=False)
        embed.add_field(name="Reason", value=(reason or "—")[:1024], inline=False)

        content_ping, allowed = modalert.mod_ping(interaction.guild)
        try:
            await alert.send(content=content_ping, embed=embed, allowed_mentions=allowed)
        except discord.HTTPException:
            await interaction.followup.send("⚠️ Couldn't post the report. Tell an admin.", ephemeral=True)
            return

        await interaction.followup.send("✅ Thanks — the mods have been notified.", ephemeral=True)
        log.info("Report from %s in %s", interaction.user, interaction.guild.name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportCog(bot))
