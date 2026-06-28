"""/vibe — a for-fun read of YOUR OWN chat style. Self-only, opt-in, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import vibe, premium
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.vibe")

MAX_MESSAGES = 80
PER_CHANNEL_SCAN = 400


class VibeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="vibe", description="A playful read of your own chat style. Just for fun.")
    @app_commands.describe(share="Post publicly instead of just to you. Default False.")
    @app_commands.guild_only()
    @premium.premium_only()
    async def vibe(self, interaction: discord.Interaction, share: bool = False) -> None:
        await interaction.response.defer(ephemeral=not share, thinking=True)
        guild = interaction.guild
        assert guild is not None

        messages = await self._collect_own_messages(guild, interaction.user)
        if len(messages) < 10:
            await interaction.followup.send(
                "Not enough of your recent messages to read your vibe (need ~10). Chat more and retry!",
                ephemeral=not share)
            return

        result = vibe.analyze(messages)
        s = result.stats
        facts = (
            f"Archetype: {result.archetype}\n"
            f"Messages analyzed: {s.messages}\n"
            f"Avg words/message: {s.words / max(s.messages,1):.1f}\n"
            f"Emoji total: {s.emoji}; top: {', '.join(e for e,_ in s.top_emoji[:3]) or 'none'}\n"
            f"Questions: {s.questions}; exclamations: {s.exclamations}; links: {s.links}\n"
            f"Favorite words: {', '.join(w for w,_ in s.top_words[:5]) or 'n/a'}"
        )
        user_prompt = (
            f"Write a warm, funny one-paragraph 'vibe check' for {interaction.user.display_name} "
            f"based ONLY on these computed stats:\n{facts}\n"
            "Tease, don't judge. End by noting it's a fun read of their style, not psychology."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("emotions"), user_prompt, web_search=False, max_tokens=350)
        except GatewayError as exc:
            log.warning("vibe narration failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.",
                                            ephemeral=not share)
            return

        embed = discord.Embed(
            title=f"✨ Vibe — {interaction.user.display_name}: {result.archetype}",
            description=reading[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="zafven • a fun read of your style, not a personality test 🎲")
        await interaction.followup.send(embed=embed, ephemeral=not share)

    async def _collect_own_messages(self, guild: discord.Guild, user: discord.abc.User) -> list[str]:
        collected: list[str] = []
        for channel in guild.text_channels:
            if len(collected) >= MAX_MESSAGES:
                break
            perms = channel.permissions_for(guild.me)
            if not (perms.read_message_history and perms.view_channel):
                continue
            try:
                async for msg in channel.history(limit=PER_CHANNEL_SCAN):
                    if msg.author.id == user.id and msg.content.strip():
                        collected.append(msg.content)
                        if len(collected) >= MAX_MESSAGES:
                            break
            except discord.HTTPException:
                continue
        return collected


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VibeCog(bot))
