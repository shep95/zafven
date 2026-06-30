"""/help — lists zafven's commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="What can zafven do?")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🜲 zafven — commands", color=discord.Color.dark_purple())
        embed.add_field(
            name="🔮 Readings (LLM-narrated, entertainment)",
            value=("`/vedic <birth_date> <birth_time> <birth_place>` — full Vedic chart + dashā\n"
                   "`/numerology <full_name> <birth_date>` — solar + lunar numerology\n"
                   "`/zodiac <birth_date>` — Chinese zodiac (year/month/day)\n"
                   "`/predict <question> [birth_date]` — ask the oracle (researches it + reads it)\n"
                   "`/vibe [share]` — a playful read of *your own* chat style\n"
                   "`/profile <member>` — public, for-fun read of a member's chat style (not psychology)\n"
                   "`/imagine <image> [question]` — describe & interpret an uploaded image\n"
                   "`/synastry <name_a> <date_a> <name_b> <date_b>` — compatibility reading"),
            inline=False)
        embed.add_field(
            name="🃏 Divination & art",
            value=("`/tarot [question] [cards]` — tarot spread\n"
                   "`/iching [question]` — cast the I Ching\n"
                   "`/dream <dream>` — symbolic dream reading\n"
                   "`/gematria decode|date|resonance <word>` — 5-cipher gematria engine\n"
                   "`/sigil <intent>` — forge a personal sigil image\n"
                   "`/portrait <full_name> <birth_date>` — frequency portrait image"),
            inline=False)
        embed.add_field(
            name="🧠 Tools",
            value=("`/research <topic>` — live web research briefing\n"
                   "`/youtube <query>` — find YouTube videos\n"
                   "`/learn <topic|youtube link>` — post a knowledge report to #knowledge\n"
                   "`/grab <link>` — pull an image/video from a link and post it here\n"
                   "`/tldr [count]` — summarize recent messages here\n"
                   "`/askdoc <pdf> <question>` — ask a question about a PDF\n"
                   "`/audit <file>` — security + quality audit of code/.zip (fix on approval)\n"
                   "`/forge <spec> [language]` — plan a feature, then write the code on approval"),
            inline=False)
        embed.add_field(
            name="💬 Just talk to her",
            value=("**@mention Zafven** (or reply to her) to **ask her anything** — she answers "
                   "questions, looks things up, jokes, and banters. She's the resident oracle (she/her).\n"
                   "She **remembers** what you tell her. `/memory` to see it, `/forget` to wipe it.\n"
                   "She has **moods** — treat her well and she warms up; be rude and she gets dry. "
                   "`/feelings` shows how she feels about you.\n"
                   "She **learns the server's vibe** and blends in (`/culture view`).\n"
                   "Admins can reshape how she acts with `/persona set`, and add custom "
                   "personality/lore/knowledge with `/brain add` (or `/brain view` the built-ins)."),
            inline=False)
        embed.add_field(
            name="🎙️ Voice",
            value=("`/vc join` — bring her into your voice channel; she **speaks her replies** "
                   "(talk to her in chat, she answers out loud).\n"
                   "`/vc listen on` — she **responds to your voice** too (experimental).\n"
                   "`/say <text>` · `/vc speak <on/off>` · `/vc leave`"),
            inline=False)
        embed.add_field(
            name="🌌 Community & events",
            value=("`/rank [member]` · `/leaderboard` — initiation XP & levels (earn roles by chatting)\n"
                   "`/capsule <message> <deliver_on> [public]` — send a message to the future\n"
                   "`/mood` — aggregate read of the server's current vibe\n"
                   "`/cipher` (mod) · `/solve <answer>` — cipher puzzle events\n"
                   "A **daily transit + koan** posts to #oracle; a weekly egregore digest on Mondays."),
            inline=False)
        embed.add_field(
            name="🛡️ Server management",
            value=("`/kick_inactive [days] [dry_run] [message]` — preview/remove inactive members "
                   "with a reinvite DM (dry-run by default)\n"
                   "`/report <message_link> [reason]` — escalate a message to the mods\n"
                   "New members get a **welcome card**; leaves are logged.\n"
                   "**Deleted messages** are logged (who/when/reply) for mods.\n"
                   "Curse words are auto-censored; spam/scam (floods, mass-mentions, "
                   "invite & scam links) is auto-removed.\n"
                   "**Cyberbullying** is warned once, then muted 30 min if it continues."),
            inline=False)
        embed.set_footer(text="Readings are for reflection & entertainment, not advice.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
