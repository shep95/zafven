"""/gematria decode|date|resonance — the AUREON gematria engine, narrated by Gemini."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import gematria, dates
from core.brain_loader import persona_system_prompt
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.gematria")


class GematriaCog(commands.Cog):
    group = app_commands.Group(name="gematria", description="Gematria cipher calculator (for fun).")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @group.command(name="decode", description="Decode a word/name across 5 ciphers with a reading.")
    @app_commands.describe(word="A word, name, or brand.")
    async def decode(self, interaction: discord.Interaction, word: str) -> None:
        a = gematria.analyze(word)
        if a is None:
            await interaction.response.send_message("❌ Give a word with letters.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        dom = gematria.planet(a.dominant_root)
        soul_p, persona_p = gematria.planet(a.soul_root or 1), gematria.planet(a.persona_root or 1)
        elem_line = " · ".join(f"{el} {n}/4" for el, n in a.elements.items() if n)
        triggers = ", ".join(f"{n} ({m})" for n, m in a.triggers) or "none"

        facts = (
            f"Word: {a.word.upper()}\n"
            f"Ciphers — Ordinal {a.ordinal}→{a.o_root}, Full-reduction {a.full}→{a.f_root}, "
            f"Reverse {a.reverse}→{a.r_root}, Chaldean {a.chaldean}→{a.c_root}\n"
            f"Dominant root: {a.dominant_root} — {dom[1]} {dom[0]} ({dom[4]}); confidence {a.confidence}%\n"
            f"Element: {a.dom_element}; signature {elem_line}\n"
            f"Soul(vowels) {a.soul}→{a.soul_root} {soul_p[0]}; Personality(consonants) {a.persona}→{a.persona_root} {persona_p[0]}\n"
            f"Trigger numbers: {triggers}; masters: {a.masters or 'none'}; hidden syllables: {a.hidden or 'none'}"
        )
        try:
            reading = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                persona_system_prompt("gematria"),
                f"Read this gematria analysis:\n{facts}\n4-6 short paragraphs.",
                web_search=False, max_tokens=1100)
        except GatewayError:
            reading = f"**{dom[1]} {dom[0]}** dominates — {dom[4]}. Element: {a.dom_element}."

        embed = discord.Embed(
            title=f"🔯 Gematria — {a.word.upper()}",
            description=reading[:4000], color=discord.Color.dark_gold())
        embed.add_field(name="Ordinal / Chaldean", value=f"{a.ordinal} / {a.chaldean}")
        embed.add_field(name="Dominant", value=f"{a.dominant_root} {dom[1]} {dom[0]} ({a.confidence}%)")
        embed.add_field(name="Element", value=a.dom_element)
        embed.add_field(name="Soul / Personality",
                        value=f"{a.soul_root} {soul_p[1]} / {a.persona_root} {persona_p[1]}")
        if a.triggers or a.masters:
            embed.add_field(name="Triggers", value=triggers + (f" · masters {a.masters}" if a.masters else ""),
                            inline=False)
        if a.hidden:
            embed.add_field(name="Hidden syllables", value=" ".join(a.hidden), inline=False)
        embed.set_footer(text="zafven • symbolic name-lore, for fun")
        await interaction.followup.send(embed=embed)

    @group.command(name="date", description="Check if a word binds to a date's numerology.")
    @app_commands.describe(word="A word or event name.", on="Date, e.g. 2025-09-26")
    async def date(self, interaction: discord.Interaction, word: str, on: str) -> None:
        try:
            d = dates.parse_date(on)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        ds = gematria.date_sync(word, d)
        if ds is None:
            await interaction.response.send_message("❌ Give a word with letters.", ephemeral=True)
            return
        wp, dp = gematria.planet(ds.word_root), gematria.planet(ds.date_root)
        verdicts = {
            "bind": ("🔗 PERFECT BIND", discord.Color.green(),
                     f"**{word.upper()}** (root {ds.word_root} {wp[0]}) and {d.isoformat()} (root "
                     f"{ds.date_root} {dp[0]}) share a root — the name is anchored to this date."),
            "harmonic": ("⚡ HARMONIC", discord.Color.gold(),
                         f"Word root {ds.word_root} ({wp[0]}) and date root {ds.date_root} ({dp[0]}) are "
                         "compatible — a favourable window, not a perfect bind."),
            "misaligned": ("◌ MISALIGNED", discord.Color.greyple(),
                           f"Word root {ds.word_root} ({wp[0]}) and date root {ds.date_root} ({dp[0]}) "
                           f"diverge. For a clean bind, pick a date that reduces to {ds.word_root}."),
        }
        title, color, body = verdicts[ds.verdict]
        embed = discord.Embed(title=f"📅 Date Sync — {title}", description=body, color=color)
        embed.set_footer(text="zafven • for fun")
        await interaction.response.send_message(embed=embed)

    @group.command(name="resonance", description="Find power words that share a word's frequency.")
    @app_commands.describe(word="A word to match.")
    async def resonance(self, interaction: discord.Interaction, word: str) -> None:
        r = gematria.resonance(word)
        if r is None:
            await interaction.response.send_message("❌ Give a word with letters.", ephemeral=True)
            return
        p = gematria.planet(r.root)
        embed = discord.Embed(
            title=f"🪞 Resonance — root {r.root} {p[1]} {p[0]}",
            description=f"Words sharing the **{p[0]}** frequency ({p[4]}).", color=discord.Color.purple())
        if r.exact:
            embed.add_field(name="Exact resonance (same total)",
                            value=", ".join(f"{w} ({v})" for w, v in r.exact)[:1024], inline=False)
        rootm = ", ".join(w for w, _ in r.root_matches[:20]) or "none in library"
        embed.add_field(name=f"Root resonance ({p[0]})", value=rootm[:1024], inline=False)
        embed.set_footer(text="zafven • for fun")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GematriaCog(bot))
