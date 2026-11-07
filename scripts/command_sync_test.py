"""Offline command schema, publication, retirement and directory checks."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discord
from discord import app_commands
import bot as application
from core.command_sync import CommandSync
from core.command_directory import CommandPages, directory_entries, send_directory
from cogs.help_cog import HelpCog


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = await application.Zafven().__aenter__()
        self.addAsyncCleanup(self.bot.__aexit__, None, None, None)
        for ext in application.INITIAL_COGS:
            await self.bot.load_extension(ext)
        self.guild = NS(id=10)
        self.remote = [NS(name=c.name, type=discord.AppCommandType(c.to_dict(self.bot.tree).get('type', 1)))
                       for c in self.bot.tree.get_commands()]
        self.sync = CommandSync(self.bot)

    async def test_all_command_payloads_serialize_within_discord_limits(self):
        payloads = [c.to_dict(self.bot.tree) for c in self.bot.tree.get_commands()]
        json.dumps(payloads)
        self.assertLessEqual(sum(p.get('type', 1) == 1 for p in payloads), 100)
        self.assertLessEqual(sum(p.get('type') == 3 for p in payloads), 5)
        def check(payload):
            self.assertLessEqual(len(payload['name']), 32)
            if 'description' in payload:
                self.assertTrue(1 <= len(payload['description']) <= 100)
            self.assertLessEqual(len(payload.get('options', [])), 25)
            for option in payload.get('options', []):
                check(option)
        for payload in payloads:
            check(payload)
        names = {c.qualified_name for c in self.bot.tree.walk_commands()}
        self.assertTrue({'commands', 'help', 'synccommands', 'voicebots', 'quote', 'asher_learn', 'adapt'} <= names)
        self.assertFalse({'profile', 'strikes', 'vc listen'} & names)

    async def test_bulk_publish_uses_complete_tree_and_preserves_context_menu(self):
        with patch.object(self.bot.tree, 'sync', new_callable=AsyncMock, return_value=self.remote) as publish:
            count = await self.sync.publish()
        publish.assert_awaited_once_with()
        self.assertTrue(self.sync.published)
        self.assertEqual(count, len(self.remote))
        self.assertTrue(any(c.name == 'Quote this message' and c.type is discord.AppCommandType.message for c in self.remote))

    async def test_incomplete_api_response_not_reported_as_success(self):
        with patch.object(self.bot.tree, 'sync', new_callable=AsyncMock, return_value=self.remote[:-1]):
            with self.assertRaises(RuntimeError):
                await self.sync.publish()
        self.assertFalse(self.sync.published)

    async def test_empty_tree_never_erases_published_menu(self):
        blank = NS(tree=NS(get_commands=lambda: [], sync=AsyncMock()))
        with self.assertRaises(RuntimeError):
            await CommandSync(blank).publish()
        blank.tree.sync.assert_not_awaited()

    async def test_stale_guild_commands_removed_after_global_publication(self):
        self.sync.published = True
        with patch.object(self.bot.tree, 'fetch_commands', new_callable=AsyncMock, return_value=[NS(name='profile')]), \
             patch.object(self.bot.tree, 'sync', new_callable=AsyncMock, return_value=[]) as publish:
            self.assertTrue(await self.sync.guild(self.guild))
            self.assertFalse(self.bot.tree.get_commands(guild=self.guild))
            publish.assert_awaited_once_with(guild=self.guild)
        self.assertTrue(self.bot.tree.get_command('quote'))

    async def test_empty_guild_scope_not_written_unnecessarily(self):
        self.sync.published = True
        with patch.object(self.bot.tree, 'fetch_commands', new_callable=AsyncMock, return_value=[]) as fetch, \
             patch.object(self.bot.tree, 'sync', new_callable=AsyncMock) as publish:
            self.assertFalse(await self.sync.guild(self.guild))
            await self.sync.guild(self.guild)
            fetch.assert_awaited_once()
            publish.assert_not_awaited()
            await self.sync.guild(self.guild, force=True)
            self.assertEqual(fetch.await_count, 2)

    async def test_server_mirror_receives_all_current_commands(self):
        self.sync.published = True
        self.sync.mirror_guild_id = 10
        with patch.object(self.bot.tree, 'sync', new_callable=AsyncMock, return_value=self.remote) as publish:
            await self.sync.guild(self.guild)
        publish.assert_awaited_once_with(guild=self.guild)
        self.assertEqual({c.name for c in self.bot.tree.get_commands(guild=self.guild)}, {c.name for c in self.bot.tree.get_commands()})

    async def test_explicit_code_defined_guild_commands_preserved(self):
        @app_commands.command(name='local_test', description='A supported guild-specific command.')
        async def local(interaction: discord.Interaction):
            pass
        self.bot.tree.add_command(local, guild=self.guild)
        self.sync.published = True
        with patch.object(self.bot.tree, 'fetch_commands', new_callable=AsyncMock, return_value=[]), \
             patch.object(self.bot.tree, 'sync', new_callable=AsyncMock, return_value=[]):
            await self.sync.guild(self.guild)
        self.assertEqual(self.bot.tree.get_command('local_test', guild=self.guild), local)

    async def test_scopes_never_removed_before_globals_succeed(self):
        with patch.object(self.bot.tree, 'sync', new_callable=AsyncMock) as publish:
            with self.assertRaises(RuntimeError):
                await self.sync.guild(self.guild)
            publish.assert_not_awaited()

    async def test_failed_server_does_not_block_other_servers(self):
        self.sync.published = True
        fake = NS(tree=self.bot.tree, guilds=[NS(id=10), NS(id=20)])
        sync = CommandSync(fake)
        sync.published = True
        denied = discord.Forbidden(NS(status=403, reason='Forbidden'), 'fixture')
        with patch.object(sync, 'guild', new_callable=AsyncMock, side_effect=[denied, True]), self.assertLogs('zafven.commands', level='WARNING'):
            self.assertEqual(await sync.guilds(), 1)
        self.assertEqual(sync.guild_errors, {10: 'Forbidden'})

    async def test_failed_extension_aborts_startup_before_sync(self):
        with patch.object(self.bot.gateway, 'start', new_callable=AsyncMock), \
             patch.object(application, '_load_opus'), \
             patch.object(self.bot, 'load_extension', new_callable=AsyncMock, side_effect=RuntimeError('fixture')), \
             patch.object(self.bot.command_sync, 'publish', new_callable=AsyncMock) as publish, \
             self.assertLogs('zafven', level='ERROR'):
            with self.assertRaises(RuntimeError):
                await self.bot.setup_hook()
            publish.assert_not_awaited()

    async def test_directory_matches_effective_tree_and_has_no_retired_commands(self):
        entries = directory_entries(self.bot.tree, self.guild)
        listed = {name[1:] for name, _ in entries if name.startswith('/')}
        expected = {c.qualified_name for c in self.bot.tree.walk_commands() if not isinstance(c, app_commands.Group)}
        self.assertEqual(listed, expected)
        self.assertTrue(any(name == 'Apps → Quote this message' for name, _ in entries))
        self.assertFalse({'profile', 'vc listen', 'strikes check'} & listed)
        self.bot.tree.copy_global_to(guild=self.guild)
        self.assertEqual(directory_entries(self.bot.tree, self.guild), entries)

    async def test_dm_directory_hides_server_only_commands(self):
        names = {name for name, _ in directory_entries(self.bot.tree)}
        self.assertIn('/ask', names)
        self.assertNotIn('/vc join', names)
        self.assertNotIn('/tldr', names)
        self.assertNotIn('/learn', names)
        self.assertNotIn('/playlist start', names)

    async def test_directory_buttons_and_discord_embed_limits(self):
        entries = directory_entries(self.bot.tree, self.guild)
        view = CommandPages(entries, 7)
        self.assertTrue(view.previous.disabled)
        self.assertFalse(view.next_page.disabled)
        seen = []
        i = NS(user=NS(id=7), response=NS(edit_message=AsyncMock(), send_message=AsyncMock()))
        self.assertTrue(await view.interaction_check(i))
        for page in range(1, view.total + 1):
            self.assertLessEqual(len(view.embed()), 6000)
            self.assertLessEqual(len(view.embed().fields), 25)
            seen += [f.name for f in view.embed().fields]
            if page < view.total:
                await view.next_page.callback(i)
        self.assertEqual(seen, [e[0] for e in entries])
        self.assertTrue(view.next_page.disabled)
        await view.previous.callback(i)
        self.assertEqual(view.page, view.total - 1)
        i.user.id = 8
        self.assertFalse(await view.interaction_check(i))
        view.stop()

    async def test_long_future_entries_still_fit_pages(self):
        view = CommandPages([(str(n), 'x' * 1024) for n in range(30)], 7)
        for page in range(1, view.total + 1):
            view.page = page
            self.assertLessEqual(len(view.embed()), 6000)
        self.assertEqual(CommandPages([], 7, -1).page, 1)
        self.assertEqual(CommandPages([], 7, 900).page, 1)
        view.stop()

    async def test_commands_and_help_send_the_same_live_directory(self):
        cog = self.bot.get_cog('HelpCog')
        for command in (HelpCog.help, HelpCog.command_list):
            i = NS(guild=self.guild, user=NS(id=7), response=NS(send_message=AsyncMock()))
            await command.callback(cog, i, 2)
            kwargs = i.response.send_message.call_args.kwargs
            self.assertTrue(kwargs['ephemeral'])
            self.assertEqual(kwargs['view'].page, 2)
            kwargs['view'].stop()

    async def test_owner_refresh_denies_nonowner_without_touching_registry(self):
        i = NS(user=NS(id=7), response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        with patch.object(self.bot, 'is_owner', new_callable=AsyncMock, return_value=False), \
             patch.object(self.bot.command_sync, 'publish', new_callable=AsyncMock) as publish:
            await HelpCog.synccommands.callback(self.bot.get_cog('HelpCog'), i)
            publish.assert_not_awaited()
        self.assertIn('Only the bot', i.followup.send.call_args.args[0])

    async def test_owner_refresh_reports_server_failures(self):
        i = NS(user=NS(id=7), response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        self.bot.command_sync.guild_errors = {10: 'Forbidden'}
        with patch.object(self.bot, 'is_owner', new_callable=AsyncMock, return_value=True), \
             patch.object(self.bot.command_sync, 'publish', new_callable=AsyncMock, return_value=82), \
             patch.object(self.bot.command_sync, 'guilds', new_callable=AsyncMock, return_value=1) as guilds:
            await HelpCog.synccommands.callback(self.bot.get_cog('HelpCog'), i)
        guilds.assert_awaited_once_with(force=True)
        self.assertIn('Server refresh failures: 1', i.followup.send.call_args.args[0])

    async def test_dm_server_tools_reply_instead_of_crashing(self):
        from cogs.tools_cog import ToolsCog
        from cogs.knowledge_cog import KnowledgeCog
        for command, cog, kwargs in ((ToolsCog.tldr, self.bot.get_cog('ToolsCog'), {}),
                                     (KnowledgeCog.learn, self.bot.get_cog('KnowledgeCog'), {'source': 'topic'})):
            i = NS(guild=None, response=NS(send_message=AsyncMock()))
            await command.callback(cog, i, **kwargs)
            self.assertIn('server', i.response.send_message.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
