"""Offline public-installation, promotional-consent, and role-delegation checks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
import config
from core.community_db import CommunityDB
from core.public_bot import PublicSettings, installation_url
from cogs.public_bot_cog import PublicBotCog
from cogs.reinvite_cog import ReinviteCog
from cogs.invites_cog import InvitesCog


class PublicBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = CommunityDB(Path(self.tmp.name) / "public.sqlite3")
        self.settings = PublicSettings(self.db)
        self.bot = MagicMock()
        self.bot.is_owner = AsyncMock(return_value=True)
        self.cog = PublicBotCog(self.bot)
        self.cog.settings = self.settings
        self.mode = patch("config.PUBLIC_BOT_MODE", True)
        self.home = patch("config.HOUSEOFASHER_GUILD_ID", 10)
        self.mode.start()
        self.home.start()
        self.workers = []

    async def asyncTearDown(self):
        for worker in self.workers:
            worker.cog_unload()
        self.mode.stop()
        self.home.stop()
        self.tmp.cleanup()

    def interaction(self):
        value = MagicMock()
        value.guild.id = 10
        value.guild.owner_id = 123
        value.guild.me.guild_permissions.manage_roles = True
        value.user.id = 40
        value.user.display_name = "Taylor"
        value.user.send = AsyncMock()
        value.response.defer = AsyncMock()
        value.response.send_message = AsyncMock()
        value.followup.send = AsyncMock()
        return value

    def role(self):
        role = MagicMock(spec=discord.Role)
        role.id = 70
        role.guild.id = 10
        role.is_default.return_value = False
        role.managed = False
        role.__ge__.return_value = False
        return role

    def member(self):
        member = MagicMock(spec=discord.Member)
        member.guild.id = 10
        member.add_roles = AsyncMock()
        member.remove_roles = AsyncMock()
        return member

    def worker(self):
        worker = ReinviteCog(self.bot)
        worker.deliver.cancel()
        worker.db = self.db
        worker.public_settings = self.settings
        self.workers.append(worker)
        return worker

    def test_public_invite_scopes_and_minimum_permissions(self):
        query = parse_qs(urlparse(installation_url(999)).query)
        self.assertEqual(query["client_id"], ["999"])
        self.assertIn("bot", query["scope"][0])
        self.assertIn("applications.commands", query["scope"][0])
        permissions = discord.Permissions(int(query["permissions"][0]))
        self.assertFalse(permissions.administrator)
        self.assertFalse(permissions.manage_roles)
        self.assertTrue(permissions.send_messages)

    async def test_default_invite_response_does_not_dm_or_subscribe(self):
        interaction = self.interaction()
        await PublicBotCog.houseofasher.callback(self.cog, interaction)
        interaction.user.send.assert_not_awaited()
        self.assertIn("https://discord.gg/M9hnebRwvk", interaction.followup.send.call_args.args[0])
        self.assertFalse(await self.settings.subscribed(40))

    async def test_requested_dm_is_personalized_and_not_future_consent(self):
        interaction = self.interaction()
        await PublicBotCog.houseofasher.callback(self.cog, interaction, private=True)
        body = interaction.user.send.call_args.args[0]
        self.assertIn("Taylor", body)
        self.assertIn(config.HOUSEOFASHER_INVITE_URL, body)
        self.assertFalse(await self.settings.subscribed(40))

    async def test_closed_dm_returns_invite_without_retry(self):
        interaction = self.interaction()
        interaction.user.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "closed")
        await PublicBotCog.houseofasher.callback(self.cog, interaction, private=True)
        interaction.user.send.assert_awaited_once()
        self.assertIn(config.HOUSEOFASHER_INVITE_URL, interaction.followup.send.call_args.args[0])

    async def test_future_promotion_consent_can_be_revoked_and_survives_restart(self):
        await self.settings.consent(40, True)
        self.assertTrue(await PublicSettings(CommunityDB(self.db.path)).subscribed(40))
        await self.settings.consent(40, False)
        self.assertFalse(await self.settings.subscribed(40))

    async def test_channel_promotion_requires_local_setup(self):
        interaction = self.interaction()
        interaction.guild.get_channel.return_value = None
        await PublicBotCog.promote_houseofasher.callback(self.cog, interaction)
        self.assertIn("approve a channel", interaction.followup.send.call_args.args[0])

    async def test_approved_channel_receives_promotion_without_mentions(self):
        interaction = self.interaction()
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 90
        channel.send = AsyncMock()
        interaction.guild.get_channel.return_value = channel
        await self.settings.change(10, lambda state: state.update(promotion_channel=90))
        await PublicBotCog.promote_houseofasher.callback(self.cog, interaction)
        kwargs = channel.send.call_args.kwargs
        self.assertEqual(kwargs["view"].children[0].url, config.HOUSEOFASHER_INVITE_URL)
        self.assertFalse(kwargs["allowed_mentions"].everyone)

    async def test_unapproved_role_is_not_granted_even_by_bot_owner(self):
        interaction, role, member = self.interaction(), self.role(), self.member()
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role)
        member.add_roles.assert_not_awaited()

    async def test_nonowner_cannot_use_delegated_role_command(self):
        self.bot.is_owner.return_value = False
        interaction, role, member = self.interaction(), self.role(), self.member()
        await self.settings.change(10, lambda state: state.update(owner_roles=[70]))
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role)
        member.add_roles.assert_not_awaited()

    async def test_bot_owner_can_grant_server_approved_role(self):
        interaction, role, member = self.interaction(), self.role(), self.member()
        await self.settings.change(10, lambda state: state.update(owner_roles=[70]))
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role)
        member.add_roles.assert_awaited_once()

    async def test_bot_owner_can_remove_server_approved_role(self):
        interaction, role, member = self.interaction(), self.role(), self.member()
        await self.settings.change(10, lambda state: state.update(owner_roles=[70]))
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role, grant=False)
        member.remove_roles.assert_awaited_once()

    async def test_discord_role_hierarchy_is_not_bypassed(self):
        interaction, role, member = self.interaction(), self.role(), self.member()
        role.__ge__.return_value = True
        await self.settings.change(10, lambda state: state.update(owner_roles=[70]))
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role)
        member.add_roles.assert_not_awaited()

    async def test_cross_server_role_is_rejected(self):
        interaction, role, member = self.interaction(), self.role(), self.member()
        role.guild.id = 999
        await self.settings.change(10, lambda state: state.update(owner_roles=[70]))
        await PublicBotCog.owner_role.callback(self.cog, interaction, member, role)
        member.add_roles.assert_not_awaited()

    async def test_role_approval_cannot_exceed_callers_role_hierarchy(self):
        interaction, role = self.interaction(), self.role()
        role.__ge__.return_value = True
        await PublicBotCog.owner_role_access.callback(self.cog, interaction, role, True)
        self.assertEqual((await self.settings.get(10))["owner_roles"], [])

    async def test_batch_promotions_are_blocked_outside_home_server(self):
        worker = self.worker()
        interaction = self.interaction()
        interaction.guild.id = 999
        worker._targets = AsyncMock()
        await ReinviteCog.reinvite.callback(worker, interaction, dry_run=False)
        worker._targets.assert_not_awaited()
        self.assertIsNone(await self.db.pending_delivery())

    async def test_public_batch_targets_only_subscribed_known_users(self):
        worker = self.worker()
        guild = MagicMock(id=10)
        guild.me.guild_permissions.ban_members = False
        guild.members = [MagicMock(id=40, bot=False), MagicMock(id=41, bot=False)]
        await self.db.remember(10, 42, "Former member", present=False, source="departed")
        await self.settings.consent(40, True)
        await self.settings.consent(42, True)
        self.assertEqual(await worker._targets(guild, "all"), [40, 42])
        self.assertEqual(await worker._targets(guild, "former"), [42])
        self.assertEqual(await worker._targets(guild, "current"), [40])

    async def test_revoked_consent_stops_pending_delivery(self):
        worker = self.worker()
        self.bot.get_guild.return_value.id = 10
        await self.db.enqueue(10, "launch", [40], "promotion")
        await self.settings.consent(40, False)
        await ReinviteCog.deliver.coro(worker)
        self.assertEqual(await self.db.campaign_status(10, "launch"), {"skipped": 1})
        self.bot.fetch_user.assert_not_called()

    async def test_automatic_join_dm_is_disabled_in_public_mode(self):
        cog = InvitesCog(self.bot)
        cog._attribute = AsyncMock(return_value=None)
        member = MagicMock(bot=False)
        member.guild.id = 10
        member.send = AsyncMock()
        await cog.on_member_join(member)
        member.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
