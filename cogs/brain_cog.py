"""/brain — the owner customizes Zafven: add personality/lore/knowledge, view brains."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import custombrain
from core.brain_loader import BRAINS_DIR, load as load_brain

log = logging.getLogger("zafven.brain")

# Built-in brains the owner can read.
VIEWABLE = sorted(p.stem for p in BRAINS_DIR.glob("*.md"))


class BrainCog(commands.Cog):
    group = app_commands.Group(
        name="brain", description="Customize Zafven's personality & knowledge (owner/admin).",
        default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @group.command(name="add", description="Add custom personality / lore / knowledge to Zafven.")
    @app_commands.describe(text="What to add — a trait, a backstory detail, server lore, a fact she should know.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def add(self, interaction: discord.Interaction, text: str) -> None:
        ok = await custombrain.add(interaction.guild, text)
        if not ok:
            await interaction.response.send_message("❌ Give me something to add.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🧠 Added to Zafven's brain",
            description=f"> {text[:1000]}", color=discord.Color.purple())
        embed.set_footer(text="Layered into her personality — won't override her safety lines.")
        await interaction.response.send_message(embed=embed)

    @group.command(name="list", description="Show the custom additions on Zafven.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def list(self, interaction: discord.Interaction) -> None:
        e = await custombrain.entries(interaction.guild)
        if not e:
            await interaction.response.send_message("No custom additions yet.", ephemeral=True)
            return
        body = "\n".join(f"**{i}.** {x}" for i, x in enumerate(e, 1))
        await interaction.response.send_message(
            embed=discord.Embed(title="🧠 Custom brain additions", description=body[:4000],
                                color=discord.Color.purple()), ephemeral=True)

    @group.command(name="clear", description="Remove all custom additions (back to her defaults).")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction) -> None:
        await custombrain.clear(interaction.guild)
        await interaction.response.send_message("🧹 Cleared your custom additions.", ephemeral=True)

    @group.command(name="view", description="View one of Zafven's built-in brains.")
    @app_commands.describe(name="Which brain to read.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def view(self, interaction: discord.Interaction, name: str) -> None:
        name = name.strip().lower()
        if name not in VIEWABLE:
            await interaction.response.send_message(
                f"❌ Unknown brain. Available: {', '.join(VIEWABLE)}", ephemeral=True)
            return
        text = load_brain(name)
        file = discord.File(io.BytesIO(text.encode("utf-8")), filename=f"{name}.md")
        await interaction.response.send_message(
            content=f"🧠 **{name}** brain (read-only):", file=file, ephemeral=True)

    @view.autocomplete("name")
    async def _view_ac(self, interaction: discord.Interaction, current: str):
        cur = current.lower()
        return [app_commands.Choice(name=n, value=n) for n in VIEWABLE if cur in n][:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BrainCog(bot))
