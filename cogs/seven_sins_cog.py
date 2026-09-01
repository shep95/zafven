"""Private, humble seven-deadly-sins correction nudges."""
from __future__ import annotations

import logging
import re
import time

import discord
from discord.ext import commands

import config

log = logging.getLogger("zafven.seven_sins")


SIN_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "pride": (
        re.compile(r"\b(i'?m better than|beneath me|i am always right|you are all stupid|i never lose)\b", re.I),
        "Pride can turn confidence into contempt.",
    ),
    "envy": (
        re.compile(r"\b(why do they get|should have been mine|i deserve what they have|jealous)\b", re.I),
        "Envy can make another person's blessing feel like your injury.",
    ),
    "wrath": (
        re.compile(r"\b(i hate you|i'?ll destroy|you deserve pain|i hope you suffer|rage)\b", re.I),
        "Wrath can make justice sound like cruelty.",
    ),
    "greed": (
        re.compile(r"\b(take it all|mine mine|i need more money|never enough|hoard)\b", re.I),
        "Greed can train the heart to call excess a need.",
    ),
    "lust": (
        re.compile(r"\b(use them for sex|body count|send nudes|smash only|lust)\b", re.I),
        "Lust can reduce a person made in God's image into an object.",
    ),
    "gluttony": (
        re.compile(r"\b(binge until|consume everything|can't stop drinking|can't stop eating)\b", re.I),
        "Gluttony can turn comfort into a master.",
    ),
    "sloth": (
        re.compile(r"\b(can't be bothered|let someone else do it|too lazy|avoid responsibility)\b", re.I),
        "Sloth can disguise neglected duty as rest.",
    ),
}


class SevenSinsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_dm: dict[tuple[int, int, str], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.SEVEN_SINS_DM_ENABLED:
            return
        if message.author.bot or message.guild is None or not message.content.strip():
            return

        found = self._detect(message.content)
        if found is None:
            return
        sin, note = found
        key = (message.guild.id, message.author.id, sin)
        now = time.time()
        if now - self._last_dm.get(key, 0) < config.SEVEN_SINS_COOLDOWN_SECONDS:
            return
        self._last_dm[key] = now

        text = (
            f"Hey {message.author.display_name}, I wanted to say this privately and humbly.\n\n"
            f"What you said may be leaning toward **{sin}**. {note} If that spirit is trying "
            "to speak through your vessel, pause before answering, lower the heat, and choose "
            "the cleaner thing: truth with humility, correction without contempt, strength "
            "without domination.\n\n"
            "No shame pile-on from me. Just a quiet nudge back toward what is good."
        )
        try:
            await message.author.send(text)
        except discord.HTTPException:
            log.info("Could not DM seven-sins nudge to %s", message.author.id)

    @staticmethod
    def _detect(text: str) -> tuple[str, str] | None:
        for sin, (pattern, note) in SIN_PATTERNS.items():
            if pattern.search(text):
                return sin, note
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SevenSinsCog(bot))
