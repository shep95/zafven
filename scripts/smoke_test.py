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


class _FakeStore:
    """A dict-backed stand-in for DiscordStore (sync get, async set) so the
    intelligence layer can be tested without Discord or Gemini."""

    def __init__(self) -> None:
        self._d: dict = {}

    def get(self, ns: str, default=None):
        return self._d.get(ns, default)

    async def set(self, ns: str, data) -> None:
        self._d[ns] = data


class IntelligenceScopeMemoryTests(unittest.IsolatedAsyncioTestCase):
    """§41 isolation / scope / promotion / ON-OFF."""

    async def test_user_isolation(self) -> None:
        from core.intelligence.memory import MemoryVault
        v = MemoryVault(_FakeStore())
        await v.offer("my name is alice", user_id=1)
        await v.offer("my name is bob", user_id=2)
        self.assertTrue(any("alice" in t for t in v.retrieve_user(1, "name")))
        self.assertFalse(any("alice" in t for t in v.retrieve_user(2, "name")))

    async def test_project_isolation(self) -> None:
        from core.intelligence.memory import MemoryVault
        from core.intelligence.scope import Scope
        a, b = MemoryVault(_FakeStore()), MemoryVault(_FakeStore())
        await a.offer("this server uses supabase auth", hinted_scope=Scope.PROJECT)
        self.assertTrue(a.retrieve_project("supabase"))
        self.assertFalse(b.retrieve_project("supabase"))

    async def test_memory_off_writes_nothing(self) -> None:
        from core.intelligence.memory import MemoryVault
        v = MemoryVault(_FakeStore())
        await v.set_user_memory(7, False)
        outcome, _item = await v.offer("i prefer concise answers", user_id=7)
        self.assertEqual(outcome, "refused")
        self.assertEqual(v.user_items(7), [])

    async def test_memory_on_promotes_explicit_immediately(self) -> None:
        from core.intelligence.memory import MemoryVault
        v = MemoryVault(_FakeStore())
        outcome, _ = await v.offer("i prefer concise answers", user_id=5)
        self.assertEqual(outcome, "stored")
        self.assertTrue(v.user_items(5))

    async def test_candidate_needs_repeated_evidence(self) -> None:
        from core.intelligence.memory import MemoryVault
        v = MemoryVault(_FakeStore())
        first, _ = await v.offer("you were really helpful with the deploy today", user_id=9)
        self.assertEqual(first, "candidate")           # one observation → not durable yet
        self.assertEqual(v.user_items(9), [])
        second, _ = await v.offer("you were really helpful with the deploy today", user_id=9)
        self.assertEqual(second, "stored")             # repeated → promoted through the gate

    def test_scope_classification(self) -> None:
        from core.intelligence.memory import classify
        from core.intelligence.scope import Scope
        scope, kind, immediate = classify("i prefer short answers")
        self.assertEqual(scope, Scope.USER)
        self.assertEqual(kind, "preference")
        self.assertTrue(immediate)
        pscope, _pkind, _pi = classify("our server uses supabase")
        self.assertEqual(pscope, Scope.PROJECT)


class IntelligencePatternTests(unittest.IsolatedAsyncioTestCase):
    """§41 pattern scope / candidate / validation / versioning / failure."""

    async def test_candidate_is_not_applied_until_validated(self) -> None:
        from core.intelligence.registry import PatternRegistry
        from core.intelligence.pattern import Pattern
        reg = PatternRegistry(_FakeStore())
        await reg.add(Pattern(name="trace before patch",
                              mechanism="reproduce then trace the data flow before patching"))
        # a fresh candidate is retrievable for consideration but NOT as applicable
        self.assertEqual(reg.retrieve("trace patch flow", include_candidates=False), [])
        self.assertTrue(reg.retrieve("trace patch flow", include_candidates=True))

    async def test_outcomes_promote_then_fail(self) -> None:
        from core.intelligence.registry import PatternRegistry
        from core.intelligence.pattern import Pattern, PatternStatus
        reg = PatternRegistry(_FakeStore())
        pid = await reg.add(Pattern(name="p", mechanism="do the thing"))
        for _ in range(3):
            await reg.record_outcome(pid, True)
        self.assertEqual(reg.get(pid).status, PatternStatus.VALIDATED)
        self.assertTrue(reg.retrieve("do thing", include_candidates=False))

    async def test_versioning_never_overwrites(self) -> None:
        from core.intelligence.registry import PatternRegistry
        from core.intelligence.pattern import Pattern, PatternStatus, Relation
        reg = PatternRegistry(_FakeStore())
        pid = await reg.add(Pattern(name="v1", mechanism="first approach",
                                    status=PatternStatus.ACTIVE))
        v2 = await reg.new_version(pid, mechanism="second approach")
        self.assertEqual(v2.version, 2)
        self.assertEqual(reg.get(pid).status, PatternStatus.SUPERSEDED)  # old kept, not deleted
        self.assertIsNotNone(reg.get(pid))
        self.assertTrue(reg.relations(v2.id, Relation.SUPERSEDES))

    async def test_unknown_is_a_real_state(self) -> None:
        from core.intelligence.registry import PatternRegistry
        from core.intelligence.creator import assess_coverage, Coverage
        reg = PatternRegistry(_FakeStore())
        state, pats = assess_coverage(reg, "a totally novel problem never seen")
        self.assertEqual(state, Coverage.UNKNOWN)
        self.assertEqual(pats, [])

    async def test_failure_is_recorded(self) -> None:
        from core.intelligence.registry import PatternRegistry
        from core.intelligence.creator import AdaptivePatternCreator
        from core.intelligence.pattern import Pattern
        reg = PatternRegistry(_FakeStore())
        pid = await reg.add(Pattern(name="fragile", mechanism="assume happy path"))
        creator = AdaptivePatternCreator(reg, provider=None)
        p = await creator.record_failure(pid, "breaks when the input is empty")
        self.assertTrue(any("empty" in f for f in p.failure_modes))
        self.assertIn("empty", p.fails_under)


class IntelligenceCredentialTests(unittest.IsolatedAsyncioTestCase):
    """§21/§38 credential boundary."""

    async def test_key_masked_and_not_leaked(self) -> None:
        from core.intelligence.gateway import CredentialVault
        store = _FakeStore()
        vault = CredentialVault(store)
        await vault.set_credential("gemini", "SUPERSECRETKEY12345", "gemini-2.5-flash")
        desc = vault.describe()
        self.assertTrue(desc["configured"])
        self.assertNotIn("SUPERSECRETKEY12345", desc["masked"])
        self.assertNotIn("SUPERSECRETKEY12345", str(desc))
        # only use() yields the raw key, for provider construction
        provider, model, key = vault.use()
        self.assertEqual(key, "SUPERSECRETKEY12345")
        self.assertEqual(model, "gemini-2.5-flash")

    async def test_capability_routing_detects_unsupported(self) -> None:
        from core.intelligence.gateway import ProviderGateway, ModelCapabilities
        caps = ModelCapabilities(provider="p", model="m", image_gen=False)
        ok, why = ProviderGateway.check_capability(caps, "image_gen")
        self.assertFalse(ok)
        self.assertIn("image_gen", why)


class IntelligenceGlobalTests(unittest.IsolatedAsyncioTestCase):
    """§27/§28 global privacy + independence."""

    async def test_privacy_boundary_rejects_personal(self) -> None:
        from core.intelligence.globals import _looks_personal, _scrub
        self.assertTrue(_looks_personal("user 12345 prefers X"))
        self.assertTrue(_looks_personal("mention <@123456789012345678> here"))
        self.assertIn("mechanism", _scrub("<@123456789012345678> mechanism"))

    async def test_independence_required_for_promotion(self) -> None:
        from core.intelligence.globals import GlobalLearning
        from core.intelligence.pattern import Pattern
        from core.intelligence.scope import Scope
        gl = GlobalLearning(_FakeStore(), provider=None)  # no LLM → scrub-only abstraction
        p = Pattern(name="small change principle",
                    mechanism="prefer the smallest structural change that fixes a localized defect",
                    scope=Scope.PROJECT, success_count=6)
        # one guild only → held, not promoted
        await gl.submit_candidate(p, source_guild_id=111)
        m1 = await gl.run_monthly_cycle()
        self.assertEqual(m1["promoted"], 0)
        self.assertGreaterEqual(m1["insufficient_independence"], 1)
        # a second independent guild → now promotable
        await gl.submit_candidate(p, source_guild_id=222)
        m2 = await gl.run_monthly_cycle()
        self.assertGreaterEqual(m2["promoted"] + m2["refined"], 1)
        self.assertTrue(gl.manifests())


if __name__ == "__main__":
    unittest.main(verbosity=2)
