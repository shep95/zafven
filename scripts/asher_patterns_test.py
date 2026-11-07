"""Synthetic fixtures for author-scoped evidence extraction; no real Asher messages."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import discord
from core.community_db import CommunityDB
from core.asher_patterns import PatternRepository, PatternError, validate_profile, public_source
from core.model_gateway import ModelGateway
from cogs.asher_patterns_cog import AsherPatternsCog


class AsherPatternTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = PatternRepository(CommunityDB(Path(self.temp.name) / "test.sqlite3"))
        self.guild = MagicMock(id=10)
        self.channel = MagicMock(id=20)
        self.channel.name = "general"
        self.channel.category = None
        self.channel.parent = None
        self.channel.type = discord.ChannelType.text
        self.channel.permissions_for.return_value.view_channel = True
        self.channel.permissions_for.return_value.read_message_history = True
        self.guild.get_channel_or_thread.return_value = self.channel
        self.guild.text_channels = [self.channel]
        self.guild.threads = []
        self.bot = MagicMock()
        self.bot.get_guild.return_value = self.guild
        self.bot.is_owner = AsyncMock(return_value=False)
        self.bot.gateway.narrate = AsyncMock(return_value=self.response())
        self.cog = AsherPatternsCog(self.bot)
        self.cog.refresh.cancel()
        self.cog.repository = self.repository

    async def asyncTearDown(self):
        self.cog.cog_unload()
        self.temp.cleanup()

    def message(self, index=0):
        message = MagicMock(id=1000 + index)
        message.guild = self.guild
        message.channel = self.channel
        message.author.id = config.ASHER_USER_ID
        message.author.bot = False
        message.content = f"Synthetic test message {index}: connect the idea to a practical example and check what changes."
        message.created_at = datetime(2026, 11, 6, 12, 0, index % 60, tzinfo=timezone.utc)
        return message

    def response(self, ids=None):
        return json.dumps({"patterns": [{"name": "Concrete transfer", "observation": "Links ideas to concrete examples.",
            "method": "Explain an unfamiliar concept through a practical example, then check the limits.",
            "when_useful": "Helping someone apply an unfamiliar idea.",
            "when_not_useful": "When the analogy hides an important difference.",
            "evidence_ids": ids or ["1000", "1001"], "counterevidence_ids": []}]})

    async def seed(self, count=20):
        await self.repository.enable(10, config.ASHER_USER_ID)
        for i in range(count):
            await self.repository.record(self.message(i))

    async def test_no_collection_before_source_is_enabled(self):
        self.assertFalse(await self.repository.record(self.message()))

    async def test_exact_author_only_is_collected(self):
        await self.repository.enable(10, config.ASHER_USER_ID)
        other = self.message()
        other.author.id = config.ASHER_USER_ID + 1
        self.assertFalse(await self.repository.record(other))
        self.assertTrue(await self.repository.record(self.message()))
        self.assertEqual(len(await self.repository.samples()), 1)

    async def test_private_channels_and_memory_channels_are_excluded(self):
        await self.repository.enable(10, config.ASHER_USER_ID)
        self.channel.permissions_for.return_value.view_channel = False
        self.assertFalse(public_source(self.channel, self.guild))
        self.assertFalse(await self.repository.record(self.message()))
        self.channel.permissions_for.return_value.view_channel = True
        self.channel.category = MagicMock()
        self.channel.category.name = config.USER_MEMORY_CATEGORY
        self.assertFalse(public_source(self.channel, self.guild))

    async def test_private_threads_are_excluded(self):
        self.channel.type = discord.ChannelType.private_thread
        self.assertFalse(public_source(self.channel, self.guild))

    async def test_evidence_ids_must_exist_and_be_distinct(self):
        await self.seed()
        samples = await self.repository.samples()
        for ids in (["1000", "99999"], ["1000", "1000"]):
            with self.assertRaises(PatternError):
                validate_profile(self.response(ids), samples)

    async def test_generated_personal_details_are_not_promoted(self):
        await self.seed()
        payload = json.loads(self.response())
        payload["patterns"][0]["method"] = "Contact person@example.com"
        with self.assertRaises(PatternError):
            validate_profile(json.dumps(payload), await self.repository.samples())

    async def test_valid_patterns_are_provisional_and_persist(self):
        await self.seed()
        profile = validate_profile(self.response(), await self.repository.samples())
        await self.repository.save(profile)
        reopened = PatternRepository(CommunityDB(self.repository.db.path))
        active = await reopened.active()
        self.assertIn("provisional", active["patterns"][0]["status"])
        self.assertEqual(active["source_user_id"], str(config.ASHER_USER_ID))

    async def test_small_dataset_does_not_generate_or_activate_profile(self):
        await self.seed(5)
        with self.assertRaises(PatternError):
            await self.cog.analyze()
        self.bot.gateway.narrate.assert_not_awaited()
        self.assertIsNone(await self.repository.active())

    async def test_duplicate_content_does_not_count_as_distinct_reasoning_examples(self):
        await self.repository.enable(10, config.ASHER_USER_ID)
        for i in range(25):
            message = self.message(i)
            message.content = "Identical repost"
            await self.repository.record(message)
        with self.assertRaises(PatternError):
            await self.cog.analyze()
        self.bot.gateway.narrate.assert_not_awaited()

    async def test_analysis_uses_only_sources_and_avoids_self_generated_feedback(self):
        await self.seed()
        await self.cog.analyze()
        self.assertFalse(self.bot.gateway.narrate.call_args.kwargs["use_learned_patterns"])
        active = await self.repository.active()
        self.assertEqual(active["sample_count"], 20)
        await self.cog.analyze()
        self.bot.gateway.narrate.assert_awaited_once()

    async def test_invalid_analysis_does_not_replace_previous_profile(self):
        await self.seed()
        await self.cog.analyze()
        await self.repository.record(self.message(21))
        self.bot.gateway.narrate.return_value = "not json"
        with self.assertRaises(PatternError):
            await self.cog.analyze()
        self.assertEqual((await self.repository.active())["sample_count"], 20)

    async def test_deleted_cited_message_invalidates_active_profile(self):
        await self.seed()
        await self.cog.analyze()
        await self.repository.delete_samples([1000])
        self.assertIsNone(await self.repository.active())
        self.assertFalse(await self.repository.has_sample(1000))

    async def test_prompt_contains_methods_not_raw_source_messages_or_ids(self):
        await self.seed()
        await self.cog.analyze()
        prompt = await self.repository.active_prompt()
        self.assertIn("Concrete transfer", prompt)
        self.assertNotIn("Synthetic test message", prompt)
        self.assertNotIn("1000", prompt)
        self.assertIn("Keep your identity Zafven", prompt)

    async def test_method_corrections_survive_profile_revisions(self):
        await self.seed()
        await self.cog.analyze()
        await self.repository.correct("Examples", "Ask which context matters before choosing an analogy.", config.ASHER_USER_ID)
        self.assertIn("Ask which context", await self.repository.active_prompt())
        await self.cog.analyze()
        self.assertEqual(len(await self.repository.corrections()), 1)

    async def test_pause_stops_new_samples(self):
        await self.seed()
        await self.repository.pause(10)
        self.assertFalse(await self.repository.record(self.message(21)))
        self.assertEqual(await self.repository.samples(), [])

    async def test_reset_removes_active_methods_samples_and_corrections(self):
        await self.seed()
        await self.cog.analyze()
        await self.repository.correct("Examples", "Use simpler examples.", config.ASHER_USER_ID)
        await self.repository.reset()
        self.assertIsNone(await self.repository.active())
        self.assertEqual(await self.repository.corrections(), [])
        self.assertFalse(await self.repository.enabled(10))

    async def test_unrelated_member_cannot_change_global_learning(self):
        interaction = MagicMock()
        interaction.user.id = config.ASHER_USER_ID + 1
        interaction.response.send_message = AsyncMock()
        self.assertFalse(await self.cog.authorized(interaction))
        interaction.response.send_message.assert_awaited_once()

    async def test_asher_account_can_manage_learning_without_admin_role(self):
        interaction = MagicMock()
        interaction.user.id = config.ASHER_USER_ID
        self.assertTrue(await self.cog.authorized(interaction))

    async def test_gateway_applies_shared_methods_with_analysis_opt_out(self):
        await self.seed()
        await self.cog.analyze()
        gateway = ModelGateway()
        gateway._session = MagicMock(closed=False)
        gateway._post_with_retry = AsyncMock(return_value="answer")
        with patch("core.asher_patterns.repository", self.repository):
            await gateway.narrate("Base personality", "Help a user", web_search=False)
            text = gateway._post_with_retry.call_args.args[0]["systemInstruction"]["parts"][0]["text"]
            self.assertIn("Concrete transfer", text)
            await gateway.narrate("Extractor", "Analyze samples", use_learned_patterns=False)
            text = gateway._post_with_retry.call_args.args[0]["systemInstruction"]["parts"][0]["text"]
            self.assertNotIn("Concrete transfer", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
