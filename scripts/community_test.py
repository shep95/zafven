"""Offline persistence and event-flow tests for message archives and reinvites."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
import config
from core.community_db import CommunityDB
from core.welcome import DEFAULT_INVITATION, render_invitation
from cogs.backup_cog import BackupCog, internal_channel
from cogs.reinvite_cog import ReinviteCog, CAMPAIGN


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Preserve the original private-server queue regression scenarios.
        self.mode = patch("config.PUBLIC_BOT_MODE", False)
        self.mode.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.db = CommunityDB(self.path)
        self.bot = MagicMock()
        guild = MagicMock(id=10)
        self.bot.guilds = [guild]
        self.cogs = []

    async def asyncTearDown(self):
        for cog in self.cogs:
            cog.cog_unload()
        self.tmp.cleanup()
        self.mode.stop()

    def backup(self):
        cog = BackupCog(self.bot)
        cog.mirror.cancel()
        cog.db = self.db
        self.cogs.append(cog)
        return cog

    def reinvites(self):
        cog = ReinviteCog(self.bot)
        cog.deliver.cancel()
        cog.db = self.db
        self.cogs.append(cog)
        return cog

    def message(self):
        message = MagicMock()
        message.guild.id = 10
        message.channel.id = 20
        message.channel.name = "general"
        message.channel.category = None
        message.channel.parent = None
        message.id = 30
        message.author.id = 40
        message.author.bot = False
        message.content = "Full original content @everyone\n" + "Unicode: 🖤 " * 100
        message.created_at = datetime(2026, 11, 6, tzinfo=timezone.utc)
        message.edited_at = None
        message.reference = None
        message.attachments = []
        message.embeds = []
        message.stickers = []
        message.type = discord.MessageType.default
        message.pinned = False
        return message

    async def test_full_message_survives_reopen_and_deduplicates_history(self):
        cog = self.backup()
        message = self.message()
        await cog.on_message(message)
        await cog._record(message)
        reopened = CommunityDB(self.path)
        rows = await reopened.pending_messages()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["payload"])["content"], message.content)
        self.assertEqual((await reopened.members(10))[0]["user_id"], "40")

    async def test_dms_and_internal_backup_messages_are_not_archived(self):
        cog = self.backup()
        dm = self.message()
        dm.guild = None
        await cog.on_message(dm)
        internal = self.message()
        internal.channel.category = MagicMock()
        internal.channel.category.name = config.MESSAGE_BACKUP_CATEGORY
        await cog.on_message(internal)
        self.assertEqual(await self.db.pending_messages(), [])

    async def test_attachment_metadata_and_reply_are_preserved(self):
        cog = self.backup()
        message = self.message()
        attachment = MagicMock(id=99, filename="file.pdf", size=128)
        attachment.content_type = "application/pdf"
        attachment.url = "https://cdn.discordapp.com/test"
        attachment.proxy_url = "https://media.discordapp.net/test"
        message.attachments = [attachment]
        message.reference = MagicMock(message_id=17)
        await cog.on_message(message)
        data = json.loads((await self.db.pending_messages())[0]["payload"])
        self.assertEqual(data["reply_to"], 17)
        self.assertEqual(data["attachments"][0]["name"], "file.pdf")

    async def test_uncached_edit_and_bulk_deletion_are_recorded(self):
        cog = self.backup()
        channel = self.message().channel
        self.bot.get_guild.return_value.get_channel_or_thread.return_value = channel
        payload = MagicMock(guild_id=10, channel_id=20, message_id=30)
        payload.data = {"content": "edited text"}
        await cog.on_raw_message_edit(payload)
        bulk = MagicMock(guild_id=10, channel_id=20, message_ids={30, 31})
        await cog.on_raw_bulk_message_delete(bulk)
        events = [json.loads(row["payload"]) for row in await self.db.pending_messages()]
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["data"]["content"], "edited text")

    async def test_mirror_failure_retains_local_archive(self):
        cog = self.backup()
        await cog.on_message(self.message())
        cog._destination = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "no access"))
        await BackupCog.mirror.coro(cog)
        self.assertEqual(len(await self.db.pending_messages()), 1)

    async def test_successful_mirror_marks_rows_and_disables_mentions(self):
        cog = self.backup()
        await cog.on_message(self.message())
        destination = MagicMock()
        destination.send = AsyncMock()
        cog._destination = AsyncMock(return_value=destination)
        await BackupCog.mirror.coro(cog)
        self.assertEqual(await self.db.pending_messages(), [])
        kwargs = destination.send.call_args.kwargs
        self.assertFalse(kwargs["allowed_mentions"].everyone)
        self.assertIn(b"Full original content", kwargs["file"].fp.read())

    async def test_new_backup_channel_is_private(self):
        cog = self.backup()
        guild = MagicMock()
        guild.categories = []
        category = MagicMock()
        category.text_channels = []
        category.channels = []
        guild.create_category = AsyncMock(return_value=category)
        guild.create_text_channel = AsyncMock()
        await cog._destination(guild, "2026-11-06")
        for create in (guild.create_category, guild.create_text_channel):
            overwrites = create.call_args.kwargs["overwrites"]
            self.assertFalse(overwrites[guild.default_role].view_channel)
            self.assertTrue(overwrites[guild.me].view_channel)

    async def test_existing_public_backup_is_hardened(self):
        cog = self.backup()
        guild = MagicMock()
        category = MagicMock()
        category.name = config.MESSAGE_BACKUP_CATEGORY
        channel = MagicMock()
        channel.name = "messages-2026-11-06"
        channel.overwrites = {}
        channel.edit = AsyncMock()
        category.text_channels = [channel]
        guild.categories = [category]
        self.assertIs(await cog._destination(guild, "2026-11-06"), channel)
        self.assertFalse(channel.edit.call_args.kwargs["overwrites"][guild.default_role].view_channel)

    async def test_full_backup_category_rotates_and_remains_internal(self):
        cog = self.backup()
        guild = MagicMock()
        category = MagicMock()
        category.name = config.MESSAGE_BACKUP_CATEGORY
        category.channels = [object()] * 50
        category.text_channels = []
        guild.categories = [category]
        guild.create_category = AsyncMock()
        guild.create_text_channel = AsyncMock()
        await cog._destination(guild, "2026-11-06")
        self.assertEqual(guild.create_category.call_args.args[0], config.MESSAGE_BACKUP_CATEGORY + "-2")
        channel = self.message().channel
        channel.category = MagicMock()
        channel.category.name = config.MESSAGE_BACKUP_CATEGORY + "-2"
        self.assertTrue(internal_channel(channel))

    async def test_missing_server_records_do_not_block_other_server_archive(self):
        await self.db.archive({"event": "sent", "guild_id": 999, "content": "former guild"})
        await self.backup().on_message(self.message())
        self.assertEqual(len(await self.db.pending_messages(guild_id=10)), 1)
        self.assertEqual(len(await self.db.pending_messages(guild_id=999)), 1)

    def test_invitation_copy_preserves_requested_spelling_and_paragraphs(self):
        link = "https://discord.gg/example"
        text = render_invitation(link, DEFAULT_INVITATION)
        self.assertTrue(text.startswith("hey guys, aureon has updated the houseofasher server"))
        self.assertIn("asher doesn't think there important", text)
        self.assertIn("please have some patience's with him", text)
        self.assertIn("unique and he. he  is well known", text)
        self.assertIn("(which turns true 99%)", text)
        self.assertLess(text.index("i know asher (aureon)"), text.index("~ zafven"))
        self.assertIn("\n\n~ zafven\n\n" + link, text)
        self.assertEqual(text.count(link), 1)
        self.assertEqual(render_invitation(link, "Custom message"), "Custom message\n\n" + link)

    async def test_campaign_survives_restart_and_does_not_add_duplicates(self):
        self.assertEqual(await self.db.enqueue(10, "launch", [40, 40, 41], "invite"), 2)
        reopened = CommunityDB(self.path)
        row = await reopened.pending_delivery()
        await reopened.delivery_status(row, "sent")
        self.assertEqual(await reopened.enqueue(10, "launch", [40, 41], "invite"), 0)
        self.assertEqual(await reopened.campaign_status(10, "launch"), {"pending": 1, "sent": 1})

    async def test_cancelled_delivery_cannot_be_claimed(self):
        await self.db.enqueue(10, "launch", [40], "invite")
        row = await self.db.pending_delivery()
        await self.db.cancel_campaign(10, "launch")
        self.assertFalse(await self.db.claim_delivery(row))
        self.assertIsNone(await self.db.pending_delivery())

    async def test_claim_is_exclusive_and_interrupted_send_is_not_requeued(self):
        await self.db.enqueue(10, "launch", [40], "invite")
        row = await self.db.pending_delivery()
        self.assertTrue(await self.db.claim_delivery(row))
        self.assertFalse(await CommunityDB(self.path).claim_delivery(row))
        self.assertIsNone(await CommunityDB(self.path).pending_delivery())

    async def test_worker_delivers_exact_queued_body(self):
        cog = self.reinvites()
        user = MagicMock(bot=False)
        user.send = AsyncMock()
        self.bot.get_user.return_value = user
        body = render_invitation("https://discord.gg/example", DEFAULT_INVITATION)
        await self.db.enqueue(10, "launch", [40], body)
        await ReinviteCog.deliver.coro(cog)
        self.assertEqual(user.send.call_args.args[0], body)
        self.assertEqual(await self.db.campaign_status(10, "launch"), {"sent": 1})

    async def test_closed_dm_is_reported_failed_without_retries(self):
        cog = self.reinvites()
        user = MagicMock(bot=False)
        user.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Cannot DM"))
        self.bot.get_user.return_value = user
        await self.db.enqueue(10, "launch", [40], "invite")
        await ReinviteCog.deliver.coro(cog)
        await ReinviteCog.deliver.coro(cog)
        user.send.assert_awaited_once()
        self.assertEqual(await self.db.campaign_status(10, "launch"), {"failed": 1})

    async def test_member_departure_stays_in_directory(self):
        cog = self.reinvites()
        member = MagicMock(id=40, bot=False)
        member.guild.id = 10
        await cog.on_member_join(member)
        await cog.on_member_remove(member)
        row = (await CommunityDB(self.path).members(10))[0]
        self.assertEqual(row["present"], 0)
        self.assertEqual(row["source"], "departed")

    async def test_reinvite_preview_never_creates_links_or_queues_messages(self):
        cog = self.reinvites()
        cog._targets = AsyncMock(return_value=[40, 41])
        cog._link = AsyncMock()
        self.bot.get_cog.return_value = None
        interaction = MagicMock()
        interaction.guild.id = 10
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await ReinviteCog.reinvite.callback(cog, interaction)
        cog._link.assert_not_awaited()
        self.assertIsNone(await self.db.pending_delivery())

    async def test_batch_command_queues_once_with_replaced_invite_link(self):
        cog = self.reinvites()
        cog._targets = AsyncMock(return_value=[40, 41])
        cog._link = AsyncMock(return_value="https://discord.gg/server")
        self.bot.get_cog.return_value = None
        interaction = MagicMock()
        interaction.guild.id = 10
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await ReinviteCog.reinvite.callback(cog, interaction, dry_run=False)
        await ReinviteCog.reinvite.callback(cog, interaction, dry_run=False)
        self.assertEqual(await self.db.campaign_status(10, CAMPAIGN), {"pending": 2})
        queued = await self.db.pending_delivery()
        self.assertIn("~ zafven\n\nhttps://discord.gg/server", queued["body"])
        self.assertNotIn("{invite_link}", queued["body"])

    async def test_history_scan_records_old_author_and_finishes(self):
        cog = self.backup()
        message = self.message()
        message.guild.get_member.return_value = None
        channel = message.channel
        async def history(**kwargs):
            yield message
        async def no_threads(**kwargs):
            if False:
                yield
        channel.history = history
        channel.archived_threads = no_threads
        guild = message.guild
        guild.text_channels = [channel]
        guild.threads = []
        cog._jobs[guild.id] = None
        await cog._history(guild, 0)
        self.assertNotIn(guild.id, cog._jobs)
        self.assertEqual(len(await self.db.pending_messages()), 1)
        self.assertEqual((await self.db.members(guild.id))[0]["present"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
