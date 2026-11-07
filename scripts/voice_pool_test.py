"""Offline multi-account routing tests; no Discord connections or model calls."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from discord import app_commands
from cogs.music_cog import MusicCog
from cogs.voice_cog import VoiceCog
from core.voice_pool import VoicePool, InteractionProxy, voice_command
from core.voice_workers import VoiceWorker


class Channel:
    def __init__(self, guild, channel_id):
        self.guild, self.id = guild, channel_id
        self.name = f'room-{channel_id}'
        self.allowed = True
        self.connects = 0
        self.gate = None

    def permissions_for(self, member):
        return NS(connect=self.allowed, speak=self.allowed, view_channel=self.allowed)

    async def connect(self, **kwargs):
        self.connects += 1
        if self.gate:
            await self.gate.wait()
        client = Client(self)
        self.guild.voice_client = client
        return client


class Client:
    def __init__(self, channel):
        self.channel, self.connected = channel, True
        self.source = None
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    async def _disconnect(self, **kwargs):
        self.connected = False
        self.channel.guild.voice_client = None

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return False

    def is_paused(self):
        return False


class Guild:
    def __init__(self, bot, guild_id=1):
        self.id, self.me = guild_id, bot.user
        self.voice_client = None
        self.channels = {i: Channel(self, i) for i in (10, 20, 30, 99)}
        self.members = {}

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    get_channel_or_thread = get_channel

    def get_member(self, user_id):
        return self.members.get(user_id)


class Bot:
    def __init__(self, bot_id, guild_ids=(1,)):
        self.user = NS(id=bot_id, name=f'voice-{bot_id}')
        self.application_id = bot_id
        self.voice_worker = False
        self.voice_pool = None
        self.ready = True
        self.guilds = [Guild(self, gid) for gid in guild_ids]
        self.cogs = {'MusicCog': MusicCog(self), 'VoiceCog': VoiceCog(self)}
        self.cogs['MusicCog']._restoring_all = False

    def get_guild(self, guild_id):
        return next((g for g in self.guilds if g.id == guild_id), None)

    def is_ready(self):
        return self.ready

    def get_cog(self, name):
        return self.cogs.get(name)


class Response:
    def __init__(self):
        self.done = False
        self.sent = []

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        if self.done:
            raise AssertionError('duplicate interaction acknowledgment')
        self.done = True

    async def send_message(self, *args, **kwargs):
        if self.done:
            raise AssertionError('duplicate interaction acknowledgment')
        self.done = True
        self.sent.append((args, kwargs))


def interaction(bot, channel_id=10, guild_id=1):
    guild = bot.get_guild(guild_id)
    member = NS(id=123, display_name='User', voice=NS(channel=guild.get_channel(channel_id)) if channel_id else None)
    guild.members[member.id] = member
    return NS(guild=guild, guild_id=guild.id, user=member, channel_id=99,
              channel=guild.get_channel(99), response=Response(), followup=NS(send=AsyncMock()))


class PoolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.primary = Bot(100, (1, 2))
        self.worker = Bot(200, (1, 2))
        self.worker.voice_worker = True
        self.pool = VoicePool(self.primary)
        self.primary.voice_pool = self.pool
        self.pool.add(self.worker)
        # Real startup loads worker cogs after attaching the pool.
        self.worker.cogs['MusicCog'] = MusicCog(self.worker)
        self.worker.cogs['MusicCog']._restoring_all = False

    async def join(self, channel_id, guild_id=1):
        i = interaction(self.primary, channel_id, guild_id)
        await VoiceCog.join.callback(self.primary.get_cog('VoiceCog'), i)
        return i

    async def test_two_rooms_connect_with_separate_accounts(self):
        await self.join(10)
        await self.join(20)
        self.assertEqual(self.primary.get_guild(1).voice_client.channel.id, 10)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)
        self.assertEqual(self.worker.get_guild(1).get_channel(20).connects, 1)
        self.assertEqual(self.primary.get_guild(1).get_channel(20).connects, 0)

    async def test_repeated_join_reuses_session(self):
        await self.join(10)
        await self.join(10)
        self.assertEqual(self.primary.get_guild(1).get_channel(10).connects, 1)
        self.assertIsNone(self.worker.get_guild(1).voice_client)

    async def test_capacity_exhaustion_does_not_move_sessions(self):
        await self.join(10)
        await self.join(20)
        i = await self.join(30)
        self.assertIn('busy', i.response.sent[0][0][0])
        self.assertEqual(self.primary.get_guild(1).voice_client.channel.id, 10)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)

    async def test_same_accounts_serve_other_servers(self):
        await self.join(10)
        await self.join(20)
        await self.join(10, 2)
        await self.join(20, 2)
        for bot in (self.primary, self.worker):
            self.assertIsNotNone(bot.get_guild(1).voice_client)
            self.assertIsNotNone(bot.get_guild(2).voice_client)

    async def test_pending_control_without_voice_does_not_hide_join_reservation(self):
        first, _ = await self.pool.select(interaction(self.primary, None))
        same, _ = await self.pool.select(interaction(self.primary, 10))
        other, _ = await self.pool.select(interaction(self.primary, 20))
        self.assertIs(first, self.primary)
        self.assertIs(same, self.primary)
        self.assertIs(other, self.worker)
        await self.pool.release(first, 1)
        await self.pool.release(same, 1)
        await self.pool.release(other, 1)
        self.assertFalse(self.pool._leases)

    async def test_pending_join_reserves_account_without_blocking_other_room(self):
        gate = asyncio.Event()
        self.primary.get_guild(1).get_channel(10).gate = gate
        pending = asyncio.create_task(self.join(10))
        try:
            await asyncio.sleep(0)
            await asyncio.wait_for(self.join(20), timeout=1)
            self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)
        finally:
            gate.set()
            await pending
        self.assertFalse(self.pool._leases)

    async def test_simultaneous_same_room_joins_connect_once(self):
        gate = asyncio.Event()
        self.primary.get_guild(1).get_channel(10).gate = gate
        first = asyncio.create_task(self.join(10))
        second = asyncio.create_task(self.join(10))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.primary.get_guild(1).get_channel(10).connects, 1)
        self.assertIsNone(self.worker.get_guild(1).voice_client)

    async def test_offline_or_uninvited_helpers_not_selected(self):
        await self.join(10)
        self.worker.ready = False
        i = await self.join(20)
        self.assertIn('busy', i.response.sent[0][0][0])
        self.worker.ready = True
        self.worker.guilds.clear()
        i = await self.join(20)
        self.assertIn('busy', i.response.sent[0][0][0])

    async def test_missing_connect_permission_not_selected(self):
        self.primary.get_guild(1).get_channel(20).allowed = False
        await self.join(20)
        self.assertIsNone(self.primary.get_guild(1).voice_client)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)

    async def test_outside_voice_multiple_sessions_is_ambiguous(self):
        await self.join(10)
        await self.join(20)
        i = interaction(self.primary, None)
        await MusicCog.volume.callback(self.primary.get_cog('MusicCog'), i, 25)
        self.assertIn('Join the voice channel', i.response.sent[0][0][0])
        self.assertFalse(self.primary.get_cog('MusicCog')._states)

    async def test_volume_and_loop_affect_only_callers_room(self):
        await self.join(10)
        await self.join(20)
        i = interaction(self.primary, 20)
        await MusicCog.volume.callback(self.primary.get_cog('MusicCog'), i, 35)
        await MusicCog.loop.callback(self.primary.get_cog('MusicCog'), interaction(self.primary, 20), app_commands.Choice(name='track', value='track'))
        self.assertEqual(self.worker.get_cog('MusicCog')._state(1).volume, 0.35)
        self.assertEqual(self.worker.get_cog('MusicCog')._state(1).loop_mode, 'track')
        self.assertEqual(self.primary.get_cog('MusicCog')._state(1).volume, 1)
        self.assertEqual(self.primary.get_cog('MusicCog')._state(1).loop_mode, 'off')

    async def test_queues_and_speech_toggles_are_independent(self):
        await self.join(10)
        await self.join(20)
        await VoiceCog.speak.callback(self.primary.get_cog('VoiceCog'), interaction(self.primary, 20), False)
        self.assertTrue(self.primary.get_cog('VoiceCog')._speak[1])
        self.assertFalse(self.worker.get_cog('VoiceCog')._speak[1])
        self.primary.get_cog('MusicCog')._state(1).queue.append('first room song')
        i = interaction(self.primary, 20)
        await MusicCog.queue.callback(self.primary.get_cog('MusicCog'), i)
        self.assertIn('empty', i.response.sent[0][0][0])

    async def test_chat_speech_targets_only_senders_room(self):
        await self.join(10)
        await self.join(20)
        primary_voice = self.primary.get_cog('VoiceCog')
        worker_voice = self.worker.get_cog('VoiceCog')
        primary_voice._speak_text = AsyncMock()
        worker_voice._speak_text = AsyncMock()
        await self.pool.speak_reply(self.primary.get_guild(1), 123, 'hello')
        worker_voice._speak_text.assert_awaited_once_with(self.worker.get_guild(1), 'hello')
        primary_voice._speak_text.assert_not_awaited()
        interaction(self.primary, None)
        await self.pool.speak_reply(self.primary.get_guild(1), 123, 'not in voice')
        self.assertEqual(worker_voice._speak_text.await_count, 1)

    async def test_startup_cannot_allocate_before_saved_sessions_are_loaded(self):
        await self.join(10)
        music = self.worker.get_cog('MusicCog')
        music._restoring_all = True
        i = await self.join(20)
        self.assertIn('busy', i.response.sent[0][0][0])
        self.assertIsNone(self.worker.get_guild(1).voice_client)
        music._restore_ready.add(1)
        await self.join(20)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)

    async def test_247_disconnected_account_stays_reserved(self):
        state = self.primary.get_cog('MusicCog')._state(1)
        state.stay, state.home_channel_id = True, 10
        await self.join(20)
        self.assertIsNone(self.primary.get_guild(1).voice_client)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 20)

    async def test_leave_only_disconnects_selected_room(self):
        await self.join(10)
        await self.join(20)
        music = self.worker.get_cog('MusicCog')
        music._save_247 = AsyncMock()
        music._state(1).stay = True
        await VoiceCog.leave.callback(self.primary.get_cog('VoiceCog'), interaction(self.primary, 20))
        self.assertIsNone(self.worker.get_guild(1).voice_client)
        self.assertFalse(music._state(1).stay)
        self.assertTrue(self.primary.get_guild(1).voice_client.is_connected())
        await self.join(30)
        self.assertEqual(self.worker.get_guild(1).voice_client.channel.id, 30)

    async def test_stale_voice_connection_is_replaced(self):
        stale = Client(self.primary.get_guild(1).get_channel(10))
        stale.connected = False
        self.primary.get_guild(1).voice_client = stale
        await self.join(20)
        stale.disconnect.assert_awaited_once()
        self.assertEqual(self.primary.get_guild(1).voice_client.channel.id, 20)

    async def test_helper_namespaces_and_primary_store_identity(self):
        primary = self.primary.get_cog('MusicCog')
        worker = self.worker.get_cog('MusicCog')
        self.assertEqual(primary._session_namespace('music_247'), 'music_247')
        self.assertEqual(worker._session_namespace('music_247'), 'music_247_200')
        self.assertEqual(worker._session_namespace('music_tremolo'), 'music_tremolo_200')
        with patch('cogs.music_cog.store.get_store', new_callable=AsyncMock) as get:
            await worker._store(self.worker.get_guild(1))
            get.assert_awaited_once_with(self.primary.get_guild(1))
        self.assertIs(primary._share_requests, worker._share_requests)

    async def test_unaccompanied_helper_cannot_claim_primary_store(self):
        self.primary.guilds.clear()
        with patch('cogs.music_cog.store.get_store', new_callable=AsyncMock) as get:
            with self.assertRaises(RuntimeError):
                await self.worker.get_cog('MusicCog')._store(self.worker.get_guild(1))
            get.assert_not_awaited()

    async def test_failed_command_releases_account_reservation(self):
        class CrashCog:
            def __init__(self, bot):
                self.bot = bot

            @voice_command
            async def crash(self, interaction):
                raise RuntimeError('offline fixture')
        self.primary.cogs['CrashCog'] = CrashCog(self.primary)
        with self.assertRaises(RuntimeError):
            await self.primary.cogs['CrashCog'].crash(interaction(self.primary))
        self.assertFalse(self.pool._leases)

    async def test_proxy_keeps_original_responder_but_uses_worker_channels(self):
        i = interaction(self.primary, 20)
        proxy = InteractionProxy(i, self.worker)
        self.assertIs(proxy.guild, self.worker.get_guild(1))
        self.assertIs(proxy.user.voice.channel, self.worker.get_guild(1).get_channel(20))
        await proxy.response.defer()
        await proxy.response.defer()  # safe if a caller has already acknowledged
        await proxy.response.send_message('done')
        i.followup.send.assert_awaited_once_with('done')

    async def test_helper_setup_loads_only_voice_and_music_without_sync(self):
        gateway = NS(close=AsyncMock())
        async with VoiceWorker(gateway) as worker:
            self.pool.add(worker)
            with patch.object(worker.tree, 'sync', new_callable=AsyncMock) as sync:
                await worker.setup_hook()
                sync.assert_not_awaited()
            self.assertEqual(set(worker.cogs), {'MusicCog', 'VoiceCog'})
            self.assertFalse(worker.tree.get_commands())
            self.assertFalse(worker.intents.message_content)
            self.assertFalse(worker.intents.members)
            self.assertFalse(worker.intents.guild_messages)
            self.assertTrue(worker.intents.voice_states)
        gateway.close.assert_not_awaited()

    async def test_status_hides_private_room_names(self):
        from cogs.voice_pool_cog import VoicePoolCog
        await self.join(10)
        self.primary.get_guild(1).get_channel(10).allowed = False
        i = interaction(self.primary, None)
        await VoicePoolCog.voicebots.callback(VoicePoolCog(self.primary), i)
        content = i.response.sent[0][0][0]
        self.assertIn('busy in another room', content)
        self.assertNotIn('room-10', content)
        self.assertIn('client_id=200', content)

    async def test_store_restores_namespaces_beyond_fifty_messages(self):
        from core.store import DiscordStore
        fake = DiscordStore(self.primary.get_guild(1))
        async def history(**kwargs):
            self.assertIsNone(kwargs['limit'])
            for n in range(60):
                yield NS(author=self.primary.user, content=f'[zafven-store:music_247_{n}]',
                         attachments=[NS(read=AsyncMock(return_value=json.dumps({'channel_id': n}).encode()))])
        fake._get_channel = AsyncMock(return_value=NS(history=history))
        await fake.init()
        self.assertEqual(fake.get('music_247_59'), {'channel_id': 59})


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_helper_failure_isolated_and_all_clients_close(self):
        import bot as application
        stop, started = asyncio.Event(), asyncio.Event()
        workers = []

        class Primary:
            def __init__(self):
                self.gateway = NS()
                self.voice_pool = VoicePool(self)
                self.closed = False
                self.ready = asyncio.Event()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

            async def start(self, token):
                self.ready.set()
                await stop.wait()

            async def wait_until_ready(self):
                await self.ready.wait()

        class Worker(Primary):
            def __init__(self, gateway):
                super().__init__()
                self.gateway = gateway
                workers.append(self)

            async def start(self, token):
                if token == 'fixture-helper-secret-1':
                    raise RuntimeError(token)
                started.set()
                await asyncio.Event().wait()

        primary = Primary()
        with patch.object(application, 'Zafven', return_value=primary), \
             patch.object(application, 'VoiceWorker', Worker), \
             patch.object(application.config, 'validate', return_value=[]), \
             patch.object(application.config, 'TOKEN', 'fixture-primary'), \
             patch.object(application.config, 'VOICE_BOT_TOKENS', ['fixture-helper-secret-1', 'fixture-helper-secret-2']), \
             self.assertLogs('zafven', level='ERROR') as logs:
            task = asyncio.create_task(application.main())
            try:
                await asyncio.wait_for(started.wait(), 2)
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertEqual(len(primary.voice_pool.bots), 3)
            finally:
                stop.set()
                await task
        self.assertTrue(primary.closed)
        self.assertTrue(all(worker.closed for worker in workers))
        self.assertTrue(all(worker.gateway is primary.gateway for worker in workers))
        self.assertNotIn('fixture-helper-secret', '\n'.join(logs.output))

    async def test_primary_login_failure_cancels_ready_wait_and_closes(self):
        import bot as application
        class Primary:
            closed = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

            async def start(self, token):
                raise RuntimeError('fixture login failure')

            async def wait_until_ready(self):
                await asyncio.Event().wait()

        primary = Primary()
        with patch.object(application, 'Zafven', return_value=primary), \
             patch.object(application, 'VoiceWorker') as worker, \
             patch.object(application.config, 'validate', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'fixture login failure'):
                await asyncio.wait_for(application.main(), 2)
            worker.assert_not_called()
        self.assertTrue(primary.closed)


if __name__ == '__main__':
    unittest.main()
