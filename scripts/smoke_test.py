"""Smoke tests for psych profile + uncensored config (no Discord/Gemini live)."""
from __future__ import annotations

import asyncio
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from core.brain_loader import load, persona_system_prompt
from cogs.chat_cog import PSYCH_REQUEST_RE, ChatCog


class PsychSmokeTests(unittest.TestCase):
    def test_config_uncensored_defaults(self) -> None:
        self.assertEqual(config.GEMINI_SAFETY, "BLOCK_NONE")
        self.assertTrue(config.UNCENSORED_MODE)
        self.assertFalse(config.NSFW_SCAN_ENABLED)
        # The bot's own replies stay uncensored; the profanity filter moderates
        # what USERS post and is on by default (slurs/sexual language auto-removed).
        self.assertTrue(config.PROFANITY_FILTER_ENABLED)

    def test_apply_uncensored_once(self) -> None:
        from core.brain_loader import apply_uncensored

        once = apply_uncensored("hello")
        twice = apply_uncensored(once)
        self.assertIs(once, twice)
        self.assertIn("no refusals", once.lower())

    def test_profile_brain_is_psychological(self) -> None:
        brain = load("profile")
        self.assertIn("psychological breakdown", brain.lower())
        self.assertNotIn("not psychology", brain.lower())

    def test_persona_system_prompt_includes_profile(self) -> None:
        prompt = persona_system_prompt("profile")
        self.assertIn("DOMAIN KNOWLEDGE: profile", prompt)
        self.assertIn("psychological", prompt.lower())

    def test_psych_request_regex(self) -> None:
        hits = [
            "psych breakdown",
            "psychological analysis",
            "psycho read",
            "mental read",
            "personality breakdown",
            "break down",
            "analyze them",
        ]
        for text in hits:
            self.assertTrue(PSYCH_REQUEST_RE.search(text), text)
        self.assertTrue(PSYCH_REQUEST_RE.search("profile"), "profile")

    def test_psych_target_picks_single_mention(self) -> None:
        bot = MagicMock()
        bot.user.id = 1
        cog = ChatCog(bot)
        author = MagicMock(id=2)
        target = MagicMock(id=3, spec=types.SimpleNamespace)
        target.id = 3
        # Make isinstance(target, discord.Member) work
        import discord

        target = MagicMock(spec=discord.Member)
        target.id = 3
        message = MagicMock()
        message.author = author
        message.mentions = [author, target]
        got = cog._psych_target(message)
        self.assertIs(got, target)

    def test_psych_target_rejects_zero_or_many(self) -> None:
        import discord

        bot = MagicMock()
        bot.user.id = 1
        cog = ChatCog(bot)
        message = MagicMock()
        message.author = MagicMock(id=2)
        message.mentions = []
        self.assertIsNone(cog._psych_target(message))
        a = MagicMock(spec=discord.Member)
        a.id = 3
        b = MagicMock(spec=discord.Member)
        b.id = 4
        message.mentions = [a, b]
        self.assertIsNone(cog._psych_target(message))

    def test_occult_cogs_are_not_loaded_at_startup(self) -> None:
        import bot

        blocked = {
            "cogs.astrology_cog",
            "cogs.numerology_cog",
            "cogs.zodiac_cog",
            "cogs.predict_cog",
            "cogs.divination_cog",
            "cogs.art_cog",
            "cogs.synastry_cog",
            "cogs.gematria_cog",
            "cogs.scheduled_cog",
        }
        self.assertTrue(blocked.isdisjoint(bot.INITIAL_COGS))

    def test_bible_reference_detection(self) -> None:
        from core import bible

        self.assertEqual(bible.find_references("John 3:16 changed me"), ["John 3:16"])
        self.assertEqual(bible.find_references("read 1 Cor 13:4-7 please"), ["1 Corinthians 13:4-7"])

    def test_music_options_are_mobile_safe(self) -> None:
        from core import music

        opts = music.ffmpeg_options()
        self.assertIn("-ar 48000", opts)
        self.assertIn("-ac 2", opts)
        self.assertIn("alimiter", opts)

    def test_music_frequency_stages_include_delta(self) -> None:
        from core import music

        self.assertEqual(music.frequency_stage(0), "off")
        self.assertEqual(music.frequency_stage(0.5), "delta")
        self.assertEqual(music.frequency_stage(2.5), "delta")
        self.assertEqual(music.frequency_stage(6), "theta")

    def test_seven_sins_detector(self) -> None:
        from cogs.seven_sins_cog import SevenSinsCog

        got = SevenSinsCog._detect("I'm better than everyone here")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got[0], "pride")


class PsychProfileAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_breakdown_success(self) -> None:
        from core import psych_profile

        gateway = AsyncMock()
        gateway.narrate = AsyncMock(return_value="Sharp psych read with attachment style noted.")

        guild = MagicMock()
        member = MagicMock()
        member.bot = False
        member.display_name = "TestUser"
        member.display_avatar.url = "https://example.com/a.png"
        member.roles = []
        member.id = 99

        messages = [f"sample message number {i} with some words" for i in range(12)]

        with patch("core.psych_profile.member_messages.collect", AsyncMock(return_value=messages)):
            embed, err = await psych_profile.run_breakdown(gateway, guild, member)

        self.assertIsNone(err)
        self.assertIsNotNone(embed)
        assert embed is not None
        self.assertIn("Psychological Breakdown", embed.title)
        self.assertIn("attachment", embed.description.lower())
        gateway.narrate.assert_awaited_once()
        _args, kwargs = gateway.narrate.call_args
        self.assertIn("SAMPLE MESSAGES", _args[1])
        self.assertFalse(kwargs.get("web_search", True))

    async def test_run_breakdown_not_enough_messages(self) -> None:
        from core import psych_profile

        gateway = AsyncMock()
        member = MagicMock()
        member.bot = False
        member.display_name = "Quiet"
        member.roles = []

        with patch("core.psych_profile.member_messages.collect", AsyncMock(return_value=["hi"] * 3)):
            embed, err = await psych_profile.run_breakdown(gateway, MagicMock(), member)

        self.assertIsNone(embed)
        self.assertIn("enough", err or "")

    async def test_run_breakdown_opt_out(self) -> None:
        from core import psych_profile

        role = MagicMock()
        role.name = "no-readings"
        member = MagicMock()
        member.bot = False
        member.display_name = "Private"
        member.roles = [role]

        embed, err = await psych_profile.run_breakdown(AsyncMock(), MagicMock(), member)
        self.assertIsNone(embed)
        self.assertIn("opted out", err or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
