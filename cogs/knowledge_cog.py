"""/youtube and /learn — find videos and build knowledge reports for the server.

/youtube <query>  — post relevant YouTube video links.
/learn <source>   — a YouTube link → fetch + summarize its transcript; or a topic
                    → web-researched explainer. Posts an "intelligence report" to
                    a public #knowledge channel for friends to learn from.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import youtube, textsplit
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.knowledge")

REPORT_SYSTEM = (
    "You write clear, accurate educational 'intelligence reports' for people learning a topic. "
    "Structure it: a one-line summary, then ## Overview, ## Key concepts, ## How it works, "
    "## Notable details, ## Takeaways. Be factual and well-organised. When given a transcript, "
    "summarise its ACTUAL content faithfully — don't invent. Plain, teachable language."
)


class KnowledgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _knowledge_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        existing = discord.utils.get(guild.text_channels, name=config.KNOWLEDGE_CHANNEL)
        if existing:
            return existing
        if not guild.me.guild_permissions.manage_channels:
            return None
        try:
            return await guild.create_text_channel(config.KNOWLEDGE_CHANNEL, reason="zafven knowledge library")
        except discord.HTTPException:
            return None

    @app_commands.command(name="youtube", description="Find YouTube videos on a topic.")
    @app_commands.describe(query="What to search for.")
    async def youtube(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        results = await youtube.search(query, max_results=5)
        if results:
            lines = [f"**{r['title']}** — {r['channel']}\n{r['url']}" for r in results]
            embed = discord.Embed(title=f"📺 YouTube — {query[:200]}", description="\n\n".join(lines)[:4000],
                                  color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return
        if results == []:  # key set but nothing found
            await interaction.followup.send("No videos found for that.")
            return
        # No API key → fall back to Gemini grounded suggestions.
        try:
            out = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                load_brain("persona"),
                f"Find 3-4 genuinely relevant YouTube videos about: {query}. Give each as 'Title — "
                "channel' then the URL on its own line. Only include links you're confident are real.",
                web_search=True, max_tokens=700)
        except GatewayError:
            await interaction.followup.send("🔌 Couldn't reach search right now. Try again shortly.")
            return
        embed = discord.Embed(title=f"📺 YouTube — {query[:200]}", description=out[:4000],
                              color=discord.Color.red())
        embed.set_footer(text="Links are AI-suggested — double-check them. Set YOUTUBE_API_KEY for verified search.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="learn", description="Build a knowledge report (from a topic or a YouTube link).")
    @app_commands.describe(source="A topic (e.g. 'vedic numerology') or a YouTube link.")
    async def learn(self, interaction: discord.Interaction, source: str) -> None:
        await interaction.response.defer(thinking=True)
        vid = youtube.extract_video_id(source)

        if vid:
            transcript = await youtube.fetch_transcript(vid)
            if not transcript:
                await interaction.followup.send(
                    "❌ I couldn't pull a transcript for that video (no captions, or YouTube blocked it). "
                    "Try a different video or give me a topic instead.")
                return
            title = "YouTube video"
            prompt = f"Write the report from this video transcript:\n\n{transcript[:80000]}"
            web = False
        else:
            title = source.strip()
            prompt = f"Write an educational report on: {source.strip()}. Research it for accuracy."
            web = True

        try:
            report = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                REPORT_SYSTEM, prompt, web_search=web, max_tokens=3500)
        except GatewayError as exc:
            log.warning("learn failed: %s", exc)
            await interaction.followup.send("🔌 Couldn't build the report right now. Try again shortly.")
            return

        channel = await self._knowledge_channel(interaction.guild)
        if channel is None:
            await interaction.followup.send("⚠️ I need a `#knowledge` channel (or Manage Channels to make one).")
            return

        header = discord.Embed(
            title=f"📚 Knowledge Report — {title[:230]}",
            description=f"Requested by {interaction.user.mention}"
                        + (f" · source: {source}" if vid else ""),
            color=discord.Color.dark_teal())
        await channel.send(embed=header)
        for part in textsplit.chunk(report, max_chunks=8):
            await channel.send(part)

        where = channel.mention if channel.id != interaction.channel_id else "this channel"
        await interaction.followup.send(f"✅ Posted the report to {where}.", ephemeral=True)
        log.info("Knowledge report (%s) by %s", title[:60], interaction.user)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(KnowledgeCog(bot))
