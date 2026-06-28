"""Cipher Events — drop an encoded phrase; first to /solve it wins."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import store, cipher

log = logging.getLogger("zafven.cipher")


class CipherCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="cipher", description="Start a new cipher puzzle for the server to solve.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def cipher(self, interaction: discord.Interaction) -> None:
        puzzle = cipher.make_puzzle()
        s = await store.get_store(interaction.guild)
        await s.set("cipher", {
            "answer": cipher.normalize(puzzle.answer),
            "method": puzzle.method,
            "solved": False,
        })
        embed = discord.Embed(
            title="🧩 Cipher Event",
            description=f"Decode this and run `/solve`:\n\n```\n{puzzle.ciphertext}\n```",
            color=discord.Color.dark_purple())
        embed.add_field(name="Hint", value=puzzle.hint)
        embed.set_footer(text="First correct /solve wins.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="solve", description="Submit your answer to the active cipher.")
    @app_commands.describe(answer="Your decoded phrase.")
    @app_commands.guild_only()
    async def solve(self, interaction: discord.Interaction, answer: str) -> None:
        s = await store.get_store(interaction.guild)
        state = s.get("cipher") or {}
        if not state or state.get("solved"):
            await interaction.response.send_message("No active cipher right now.", ephemeral=True)
            return
        if cipher.normalize(answer) == state.get("answer"):
            state["solved"] = True
            state["solved_by"] = interaction.user.id
            await s.set("cipher", state)
            await interaction.response.send_message(
                f"🎉 {interaction.user.mention} cracked the cipher — **{state['answer']}**!")
        else:
            await interaction.response.send_message("❌ Not quite. Keep decoding.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CipherCog(bot))
