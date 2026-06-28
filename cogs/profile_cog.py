"""/profile — a public, surface-level communication-style read of a member.

Deliberately built to stay on the right side of the line:
  * It reads ONLY the target's own public messages.
  * It posts PUBLICLY and @mentions the target, so it's never done behind their
    back — they see it.
  * It's a communication-style "vibe", not a psychological breakdown (the profile
    brain forbids clinical / private-fact / manipulation content).
  * Anyone with an opt-out role (PROFILE_OPTOUT_ROLES) cannot be profiled.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import vibe
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.profile")

MAX_MESSAGES = 80
PER_CHANNEL_SCAN = 400


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="A public, for-fun read of a member's chat style (not psychology).")
    @app_commands.describe(member="The member to read (they'll see it; surface style only).")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if member.bot:
            await interaction.response.send_message("❌ Bots don't have a vibe to read.", ephemeral=True)
            return
        optout = set(config.PROFILE_OPTOUT_ROLES)
        if any(r.name.lower() in optout for r in member.roles):
            await interaction.response.send_message(
                f"🔒 {member.display_name} has opted out of readings.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        assert guild is not None
        messages = await self._collect_messages(guild, member)
        if len(messages) < 10:
            await interaction.followup.send(
                f"I couldn't find enough of {member.display_name}'s recent messages (need ~10).")
            return

        result = vibe.analyze(messages)
        s = result.stats
        facts = (
            f"Member: {member.display_name}\n"
            f"Archetype: {result.archetype}\n"
            f"Messages analyzed: {s.messages} | avg words/msg: {s.words / max(s.messages,1):.1f}\n"
            f"Emoji: {s.emoji} (top: {', '.join(e for e,_ in s.top_emoji[:3]) or 'none'})\n"
            f"Questions: {s.questions} | exclamations: {s.exclamations} | links: {s.links}\n"
            f"Favorite words: {', '.join(w for w,_ in s.top_words[:5]) or 'n/a'}"
        )
        user_prompt = (
            f"Write a warm, public communication-style read of {member.display_name} from these "
            f"stats of THEIR OWN public messages only:\n{facts}\n"
            "Surface style only — no psychology, no private facts, no advice on handling them. "
            "2-3 short paragraphs."
        )

        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("profile"), user_prompt, web_search=False, max_tokens=500)
        except GatewayError as exc:
            log.warning("profile failed: %s", exc)
            await interaction.followup.send("🔌 The reading engine is unreachable right now. Try again shortly.")
            return

        embed = discord.Embed(
            title=f"🪞 Communication Vibe — {member.display_name}: {result.archetype}",
            description=reading[:4000], color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="A fun read of public chat style — not psychology. Opt out: ask for the no-readings role.")
        await interaction.followup.send(content=member.mention, embed=embed)

    async def _collect_messages(self, guild: discord.Guild, member: discord.Member) -> list[str]:
        collected: list[str] = []
        for channel in guild.text_channels:
            if len(collected) >= MAX_MESSAGES:
                break
            perms = channel.permissions_for(guild.me)
            if not (perms.read_message_history and perms.view_channel):
                continue
            try:
                async for msg in channel.history(limit=PER_CHANNEL_SCAN):
                    if msg.author.id == member.id and msg.content.strip():
                        collected.append(msg.content)
                        if len(collected) >= MAX_MESSAGES:
                            break
            except discord.HTTPException:
                continue
        return collected


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
