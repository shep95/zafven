"""/teach — the community grows Zafven's knowledge base of corrected facts.

Anyone can teach her a fact; she pulls relevant ones into future answers. Mods
prune bad entries with /unlearn. (She also learns automatically when corrected
mid-chat — see chat_cog's [[learn:]] mechanism.)
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import learned


class TeachCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="teach", description="Teach Zafven a fact she'll remember for the whole server.")
    @app_commands.describe(topic="What it's about (a few words).", fact="The correct information.")
    @app_commands.guild_only()
    async def teach(self, interaction: discord.Interaction, topic: str, fact: str) -> None:
        ok = await learned.add(interaction.guild, topic, fact, interaction.user.id)
        if not ok:
            await interaction.response.send_message("❌ Give me a fact to learn.", ephemeral=True)
            return
        embed = discord.Embed(title="📚 Learned it", color=discord.Color.teal())
        embed.add_field(name=topic[:120] or "note", value=fact[:600], inline=False)
        embed.set_footer(text="I'll use this in future answers. Mods can /unlearn it. Not advice.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="taught", description="See what the server has taught Zafven.")
    @app_commands.describe(search="Optional: filter by keyword.")
    @app_commands.guild_only()
    async def taught(self, interaction: discord.Interaction, search: str = "") -> None:
        entries = await learned.all_entries(interaction.guild)
        if search:
            s = search.lower()
            entries = [e for e in entries
                       if s in e.get("topic", "").lower() or s in e.get("fact", "").lower()]
        if not entries:
            await interaction.response.send_message(
                "Nothing in the knowledge base yet — `/teach` me something, or correct me in chat.",
                ephemeral=True)
            return
        lines = []
        for i, e in enumerate(entries):
            topic = e.get("topic", "")
            head = f"**{i}.** " + (f"*{topic}* — " if topic else "")
            lines.append(head + e["fact"][:200])
        body = "\n".join(lines)
        embed = discord.Embed(title="📚 Zafven's knowledge base",
                              description=body[:4000], color=discord.Color.teal())
        embed.set_footer(text=f"{len(entries)} fact(s) • mods can remove one with /unlearn <number>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unlearn", description="Remove a fact from the knowledge base (mods).")
    @app_commands.describe(number="The number shown in /taught.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def unlearn(self, interaction: discord.Interaction, number: int) -> None:
        gone = await learned.remove(interaction.guild, number)
        if gone is None:
            await interaction.response.send_message(
                "❌ No fact at that number — check `/taught`.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🧹 Forgot: *{(gone.get('topic') or 'note')}* — {gone['fact'][:200]}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TeachCog(bot))
