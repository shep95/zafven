"""Offline tests for the imported personality and scoped adaptive user memory."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import discord
from core.brain_loader import load
from core.community_db import CommunityDB
from core.user_memory import UserMemory, empty_state, prompt_context
from cogs.user_memory_cog import UserMemoryCog
from cogs.backup_cog import internal_channel
from cogs.chat_cog import ChatCog, ADAPT_RE, STOP_BANTER_RE


class PersonalityMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "memory.sqlite3"
        self.memory = UserMemory(CommunityDB(self.path))
        self.guild = MagicMock(id=10)
        self.guild.me.id = 777
        self.guild.text_channels = []
        self.guild.categories = []
        self.legacy = MagicMock()
        self.legacy.get.return_value = {}
        self.legacy.set = AsyncMock()
        self.patch = patch("core.store.get_store", AsyncMock(return_value=self.legacy))
        self.patch.start()
        self.cogs = []

    async def asyncTearDown(self):
        for cog in self.cogs:
            cog.cog_unload()
        self.patch.stop()
        self.tmp.cleanup()

    def cog(self):
        result = UserMemoryCog(MagicMock())
        result.mirror.cancel()
        result.memory = self.memory
        self.cogs.append(result)
        return result

    def test_imported_personality_is_renamed_and_injected(self):
        for name in ("persona", "companion"):
            text = load(name)
            self.assertNotIn("aureon", text.lower())
            self.assertIn("Zafven", text)
            self.assertIn("complaint-to-correction learning", text)
            self.assertIn("FAST", text)
            self.assertIn("model", text)
            self.assertIn("troll", text)

    async def test_memory_is_isolated_by_user_and_server(self):
        await self.memory.add(10, 20, "projects", "Private project A")
        await self.memory.add(10, 21, "projects", "Private project B")
        await self.memory.add(11, 20, "projects", "Other server project")
        state = await self.memory.load(self.guild, 20)
        self.assertEqual(state["projects"], ["Private project A"])
        self.assertNotIn("project B", prompt_context(state, 30))

    async def test_preferences_survive_restart(self):
        await self.memory.preference(10, 20, "style", "Brief answers in Spanish")
        await self.memory.preference(10, 20, "banter", "troll")
        reopened = UserMemory(CommunityDB(self.path))
        state = await reopened.load(self.guild, 20)
        self.assertEqual(state["preferences"], {"style": "Brief answers in Spanish", "banter": "troll"})

    async def test_simultaneous_changes_do_not_lose_user_notes(self):
        await asyncio.gather(*(self.memory.add(10, 20, "notes", f"note {i}") for i in range(12)))
        self.assertEqual(len((await self.memory.load(self.guild, 20))["notes"]), 12)

    async def test_recent_conversation_remains_in_source_channel(self):
        await self.memory.exchange(10, 20, 30, "Private-channel question", "Private-channel answer")
        await self.memory.exchange(10, 20, 31, "Public question", "Public answer")
        text = prompt_context(await self.memory.load(self.guild, 20), 31)
        self.assertIn("Public question", text)
        self.assertNotIn("Private-channel", text)

    async def test_legacy_notes_migrate_without_replacing_new_notes(self):
        self.legacy.get.return_value = {"20": ["Legacy note"]}
        state = await self.memory.load(self.guild, 20)
        self.assertEqual(state["notes"], ["Legacy note"])
        await self.memory.add(10, 20, "notes", "New note")
        self.assertEqual((await self.memory.load(self.guild, 20))["notes"], ["Legacy note", "New note"])

    async def test_reset_does_not_reimport_legacy_data(self):
        self.legacy.get.return_value = {"20": ["Old legacy note"]}
        await self.memory.load(self.guild, 20)
        await self.memory.preference(10, 20, "banter", "troll")
        await self.memory.clear(10, 20)
        state = await UserMemory(CommunityDB(self.path)).load(self.guild, 20)
        self.assertEqual(state, empty_state())

    async def test_note_bounds_and_preference_allowlist(self):
        await self.memory.add(10, 20, "facts", "x" * 3000)
        await self.memory.preference(10, 20, "administrator", "true")
        await self.memory.preference(10, 20, "banter", "invalid")
        state = await self.memory.load(self.guild, 20)
        self.assertEqual(len(state["facts"][0]), 1000)
        self.assertEqual(state["preferences"], {})

    async def test_memory_channel_is_private_and_excluded_from_backups(self):
        cog = self.cog()
        category = MagicMock()
        category.channels = []
        self.guild.create_category = AsyncMock(return_value=category)
        self.guild.create_text_channel = AsyncMock()
        await cog.destination(self.guild, 20)
        overwrites = self.guild.create_text_channel.call_args.kwargs["overwrites"]
        self.assertFalse(overwrites[self.guild.default_role].view_channel)
        self.assertTrue(overwrites[self.guild.me].view_channel)
        channel = MagicMock()
        channel.name = "memory-20"
        channel.category.name = config.USER_MEMORY_CATEGORY
        self.assertTrue(internal_channel(channel))

    async def test_existing_memory_channel_permissions_are_hardened(self):
        cog = self.cog()
        channel = MagicMock()
        channel.name = "memory-20"
        channel.category.name = config.USER_MEMORY_CATEGORY
        channel.overwrites = {}
        channel.edit = AsyncMock()
        self.guild.text_channels = [channel]
        self.assertIs(await cog.destination(self.guild, 20), channel)
        self.assertFalse(channel.edit.call_args.kwargs["overwrites"][self.guild.default_role].view_channel)

    async def test_channel_snapshot_is_recovered_only_for_matching_user(self):
        channel = MagicMock()
        channel.name = "memory-20"
        channel.category.name = config.USER_MEMORY_CATEGORY
        message = MagicMock()
        message.author.id = 777
        message.content = "[zafven-memory:20]"
        state = empty_state()
        state["projects"] = ["Recovered project"]
        attachment = MagicMock(size=1000)
        attachment.read = AsyncMock(return_value=json.dumps({"guild_id": "10", "user_id": "20", "state": state}).encode())
        message.attachments = [attachment]
        async def history(**kwargs):
            yield message
        channel.history = history
        self.guild.text_channels = [channel]
        self.assertEqual((await self.memory.load(self.guild, 20))["projects"], ["Recovered project"])
        self.assertEqual((await self.memory.load(self.guild, 21))["projects"], [])

    async def test_mirror_updates_one_snapshot_and_acknowledges_revision(self):
        cog = self.cog()
        await self.memory.add(10, 20, "feedback", "Be more concise")
        row = await self.memory.row(10, 20)
        channel = MagicMock(id=90)
        prior = MagicMock(id=91)
        prior.author.id = 777
        prior.content = "[zafven-memory:20]"
        prior.edit = AsyncMock(return_value=MagicMock(id=91))
        async def history(**kwargs):
            yield prior
        channel.history = history
        cog.destination = AsyncMock(return_value=channel)
        await cog.mirror_one(self.guild, row)
        payload = json.loads(prior.edit.call_args.kwargs["attachments"][0].fp.read())
        self.assertEqual(payload["state"]["feedback"], ["Be more concise"])
        self.assertEqual(await self.memory.pending(), [])

    async def test_old_acknowledgement_does_not_hide_a_newer_change(self):
        await self.memory.add(10, 20, "notes", "First")
        old_row = await self.memory.row(10, 20)
        await self.memory.add(10, 20, "notes", "Second")
        await self.memory.acknowledge(old_row, 90, 91)
        self.assertEqual(len(await self.memory.pending()), 1)

    async def test_adapt_command_changes_only_the_callers_preferences(self):
        cog = self.cog()
        interaction = MagicMock()
        interaction.guild = self.guild
        interaction.user.id = 20
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await UserMemoryCog.adapt.callback(cog, interaction, "Use short replies", "off")
        prefs = (await self.memory.load(self.guild, 20))["preferences"]
        self.assertEqual(prefs, {"style": "Use short replies", "banter": "off"})
        self.assertIsNone(await self.memory.row(10, 21))

    def test_stop_trolling_and_hidden_preference_tags(self):
        self.assertTrue(STOP_BANTER_RE.search("please stop trolling"))
        self.assertTrue(STOP_BANTER_RE.search("don't roast me"))
        self.assertEqual(ADAPT_RE.findall("ok [[adapt: tone :: casual]]"), [("tone", "casual")])
        self.assertEqual(ADAPT_RE.findall("[[adapt: administrator :: true]]"), [])

    def test_chat_prompt_contains_imported_identity_and_scoped_preferences(self):
        cog = ChatCog(MagicMock())
        state = empty_state()
        state["preferences"] = {"banter": "off", "style": "Be brief"}
        prompt = cog._system("User", [], "", "", personal=prompt_context(state, 30))
        self.assertIn("complaint-to-correction", prompt)
        self.assertIn('"banter": "off"', prompt)
        self.assertNotIn("aureon", prompt.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
