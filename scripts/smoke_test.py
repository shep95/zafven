"""Offline behavior and extension-registration checks; no live Discord/Gemini calls."""
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
    def test_config_answer_defaults(self) -> None:
        self.assertEqual(config.GEMINI_SAFETY, "BLOCK_NONE")
        self.assertTrue(config.UNCENSORED_MODE)

    def test_apply_uncensored_once(self) -> None:
        from core.brain_loader import apply_uncensored

        once = apply_uncensored("hello")
        twice = apply_uncensored(once)
        self.assertIs(once, twice)
        self.assertIn("requested subject directly", once.lower())

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


class CleanupBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 7
        interaction.guild.id = 99
        interaction.guild.owner_id = 123
        interaction.user.guild_permissions = MagicMock(
            manage_guild=False, manage_channels=False, administrator=False)
        interaction.user.roles = []
        return interaction

    async def test_all_extensions_register_without_content_policing(self):
        import bot

        async with bot.Zafven() as client:
            for extension in bot.INITIAL_COGS:
                await client.load_extension(extension)
            commands = {command.qualified_name for command in client.tree.walk_commands()}
            expected = {
                "ask", "audit", "forge", "play", "playlist share", "defaultmusic add",
                "vc join", "say", "vibe", "rank", "capsule", "cipher", "solve",
                "mood", "invite", "report", "kick_inactive", "memory", "teach",
            }
            self.assertTrue(expected <= commands, expected - commands)
            self.assertNotIn("strikes check", commands)
            self.assertNotIn("profile", commands)
            # No installed message listener may delete or timeout a posted message.
            import inspect
            for listener in client.extra_events.get("on_message", []):
                source = inspect.getsource(listener)
                self.assertNotIn("message.delete(", source)
                self.assertNotIn(".timeout(", source)
            print(f"Registered {len(client.extensions)} extensions / {len(commands)} commands and groups")

    async def test_forge_returns_code_without_button(self):
        from cogs.forge_cog import ForgeCog

        bot = MagicMock()
        bot.gateway.narrate = AsyncMock(return_value="Design\n```python\nprint('hello')\n```")
        interaction = self.interaction()
        cog = ForgeCog(bot)
        await ForgeCog.forge.callback(cog, interaction, "Build a hello world CLI", "Python")
        bot.gateway.narrate.assert_awaited_once()
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertNotIn("view", kwargs)
        self.assertIn(b"print('hello')", kwargs["file"].fp.read())

    async def test_audit_returns_report_and_fix_without_button(self):
        from cogs.audit_cog import AuditCog

        bot = MagicMock()
        bot.gateway.narrate = AsyncMock(return_value="Finding and proposed corrected code")
        attachment = MagicMock(filename="example.py", size=20)
        attachment.read = AsyncMock(return_value=b"print('hello')")
        interaction = self.interaction()
        await AuditCog.audit.callback(AuditCog(bot), interaction, attachment)
        bot.gateway.narrate.assert_awaited_once()
        self.assertIn("proposed corrected files", bot.gateway.narrate.call_args.args[1])
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertNotIn("view", kwargs)
        self.assertIn(b"proposed corrected code", kwargs["file"].fp.read())

    async def test_code_generation_failure_returns_error(self):
        from cogs.forge_cog import ForgeCog
        from core.model_gateway import GatewayError

        bot = MagicMock()
        bot.gateway.narrate = AsyncMock(side_effect=GatewayError("offline"))
        interaction = self.interaction()
        await ForgeCog.forge.callback(ForgeCog(bot), interaction, "Build a hello world CLI")
        self.assertNotIn("file", interaction.followup.send.call_args.kwargs)
        self.assertIn("unreachable", interaction.followup.send.call_args.args[0])

    async def test_audit_still_bounds_uploads(self):
        from cogs.audit_cog import AuditCog, MAX_UPLOAD_BYTES

        bot = MagicMock()
        bot.gateway.narrate = AsyncMock()
        attachment = MagicMock(size=MAX_UPLOAD_BYTES + 1)
        attachment.read = AsyncMock()
        interaction = self.interaction()
        await AuditCog.audit.callback(AuditCog(bot), interaction, attachment)
        attachment.read.assert_not_awaited()
        bot.gateway.narrate.assert_not_awaited()

    async def test_nonowner_can_edit_default_playlist(self):
        from cogs.music_cog import MusicCog

        cog = MusicCog(MagicMock())
        cog._load_default_queries = AsyncMock(return_value=[])
        cog._save_default_queries = AsyncMock()
        interaction = self.interaction()
        await MusicCog.default_add.callback(cog, interaction, "a song")
        cog._save_default_queries.assert_awaited_once_with(interaction.guild, ["a song"])

    async def test_music_controls_do_not_require_dj_permissions(self):
        from cogs.music_cog import MusicCog
        from discord import app_commands

        cog = MusicCog(MagicMock())
        interaction = self.interaction()
        await MusicCog.loop.callback(cog, interaction, app_commands.Choice(name="track", value="track"))
        self.assertEqual(cog._state(interaction.guild.id).loop_mode, "track")

    async def test_bot_created_personal_invite_credits_human_owner(self):
        from cogs.invites_cog import InvitesCog

        cog = InvitesCog(MagicMock())
        guild = MagicMock(id=99)
        member = MagicMock(id=7)
        owner = MagicMock(id=8, bot=False)
        guild.get_member.return_value = owner
        invite = MagicMock(code="personal", uses=1)
        invite.inviter.bot = True
        cog._safe_invites = AsyncMock(return_value=[invite])
        with patch("cogs.invites_cog.invites.owner_of_code", AsyncMock(return_value=8)):
            self.assertIs(await cog._attribute(guild, member), owner)

    async def test_personal_invite_does_not_credit_self(self):
        from cogs.invites_cog import InvitesCog

        cog = InvitesCog(MagicMock())
        guild = MagicMock(id=99)
        member = MagicMock(id=7, bot=False)
        guild.get_member.return_value = member
        cog._safe_invites = AsyncMock(return_value=[MagicMock(code="self", uses=1)])
        with patch("cogs.invites_cog.invites.owner_of_code", AsyncMock(return_value=7)):
            self.assertIsNone(await cog._attribute(guild, member))

    async def test_answer_style_flag_is_honored_at_gateway(self):
        from core.model_gateway import ModelGateway

        gateway = ModelGateway()
        gateway._session = MagicMock(closed=False)
        gateway._post_with_retry = AsyncMock(return_value="answer")
        with patch("config.UNCENSORED_MODE", False):
            await gateway.narrate(persona_system_prompt("profile"), "question", web_search=False)
        payload = gateway._post_with_retry.call_args.args[0]
        self.assertNotIn("[UNCENSORED ACTIVE]", payload["systemInstruction"]["parts"][0]["text"])
        with patch("config.UNCENSORED_MODE", True):
            await gateway.narrate(persona_system_prompt("profile"), "question", web_search=False)
        payload = gateway._post_with_retry.call_args.args[0]
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"].count("[UNCENSORED ACTIVE]"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
