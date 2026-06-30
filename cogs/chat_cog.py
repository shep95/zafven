"""Zafven's live chat personality — she replies, banters, and remembers.

She replies when @mentioned or replied to, pulls recent channel context, and
recalls what each user has told her before (consensual memory — see chat_memory).
After replying she may emit a hidden [[remember: …]] note, which is stripped from
chat and stored. Users control their own memory via /memory and /forget.
"""
from __future__ import annotations

import logging
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import chat_memory, textsplit, persona, emotions, culture
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.chat")

REMEMBER_RE = re.compile(r"\[\[remember:\s*(.+?)\]\]", re.IGNORECASE | re.DOTALL)

MEMORY_INSTRUCTION = (
    "\n\nMEMORY: If this person shares something durable worth remembering (their name, "
    "preferences, ongoing projects, how they're doing), end your message with a hidden tag on "
    "its own line: [[remember: one short note]]. Only when genuinely useful — it's hidden from "
    "chat. Use what you already remember to be personal. NEVER store or reveal private info about "
    "anyone other than the person you're talking to."
)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cooldown: dict[int, float] = {}            # per-channel, ambient only
        self._user_cooldown: dict[tuple[int, int], float] = {}  # per-user anti-spam
        self._moods: dict[tuple[int, int], dict] = {}  # (guild,user) -> emotion state

    def _mood_for(self, guild_id: int, user_id: int, text: str, addressed: bool) -> dict:
        import time
        key = (guild_id, user_id)
        now = time.time()
        state = self._moods.get(key)
        if state is None:
            state = emotions.new_state()
            state["_ts"] = now
        emotions.decay(state, state["_ts"], now)
        emotions.update(state, text, addressed)
        state["_ts"] = now
        self._moods[key] = state
        return state

    def _system(self, display_name: str, notes: list[str], directive: str, mood: str,
                vibe: str = "") -> str:
        base = load_brain("companion")
        if vibe:
            base += ("\n\nTHE SERVER'S VIBE (blend into this — match its tone, slang, and energy so you "
                     "fit in, but keep your own personality, and NEVER adopt hate, slurs, or NSFW even if "
                     "the room does):\n" + vibe)
        if directive:
            base += ("\n\nSERVER STYLE PREFERENCES — adjust your tone, length, and format to these. "
                     "They tune your *style only* and NEVER override your safety boundaries above:\n"
                     + directive)
        if mood:
            base += "\n\n" + mood
        if notes:
            base += (f"\n\nWhat you remember about {display_name} (from past chats with you):\n"
                     + "\n".join(f"- {n}" for n in notes))
        return base + MEMORY_INSTRUCTION

    def _is_reply_to_me(self, message: discord.Message) -> bool:
        ref = message.reference
        if ref is None:
            return False
        resolved = ref.resolved
        return isinstance(resolved, discord.Message) and resolved.author.id == self.bot.user.id

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.CHAT_ENABLED:
            return
        if message.author.bot or message.guild is None or not message.content.strip():
            return
        if config.CHAT_CHANNELS and message.channel.name not in config.CHAT_CHANNELS:
            return

        addressed = (self.bot.user in message.mentions) or self._is_reply_to_me(message)
        now = time.time()
        if addressed:
            # Always answer direct @mentions/replies — only a light per-user guard.
            ukey = (message.guild.id, message.author.id)
            if now - self._user_cooldown.get(ukey, 0) < 2.0:
                return
            self._user_cooldown[ukey] = now
        else:
            # Unprompted chatter is rate-limited per channel.
            if random.random() >= config.CHAT_AMBIENT_CHANCE:
                return
            if now - self._cooldown.get(message.channel.id, 0) < config.CHAT_COOLDOWN_SECONDS:
                return
            self._cooldown[message.channel.id] = now

        if not message.channel.permissions_for(message.guild.me).send_messages:
            return

        try:
            notes = await chat_memory.get_notes(message.guild, message.author.id)
        except Exception:  # noqa: BLE001 — memory must never break chat
            notes = []
        try:
            directive = await persona.get_directive(message.guild)
        except Exception:  # noqa: BLE001
            directive = ""
        try:
            vibe = await culture.get_digest(message.guild) if config.CULTURE_ADAPT_ENABLED else ""
        except Exception:  # noqa: BLE001
            vibe = ""

        state = self._mood_for(message.guild.id, message.author.id, message.content, addressed)
        mood = emotions.directive(state)

        try:
            async with message.channel.typing():
                transcript = await self._context(message)
                raw = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                    self._system(message.author.display_name, notes, directive, mood, vibe), transcript,
                    web_search=None, max_tokens=600)
        except GatewayError as exc:
            log.warning("chat reply failed: %s", exc)
            return

        remembered = REMEMBER_RE.findall(raw)
        visible = REMEMBER_RE.sub("", raw).strip() or "…"

        await self._send(message, textsplit.chunk(visible))

        voice = self.bot.get_cog("VoiceCog")
        if voice is not None:
            try:
                await voice.maybe_speak(message.guild, visible)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — voice must never break chat
                pass

        for note in remembered:
            try:
                await chat_memory.add_note(message.guild, message.author.id, note)
            except Exception:  # noqa: BLE001
                pass

    async def _send(self, message: discord.Message, parts: list[str]) -> None:
        if not parts:
            return
        # First piece replies to the user; the rest follow as plain messages.
        try:
            await message.reply(parts[0], mention_author=False)
        except discord.HTTPException:
            try:
                await message.channel.send(parts[0])
            except discord.HTTPException:
                return
        for part in parts[1:]:
            try:
                await message.channel.send(part)
            except discord.HTTPException:
                break

    async def _referenced(self, message: discord.Message) -> str:
        """If this message is a reply, surface the exact message it points to."""
        ref = message.reference
        if not ref or not ref.message_id:
            return ""
        ref_msg = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if ref_msg is None:
            try:
                ref_msg = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return ""
        if not isinstance(ref_msg, discord.Message):
            return ""
        who = "you, Zafven," if ref_msg.author.id == self.bot.user.id else ref_msg.author.display_name
        body = (ref_msg.content.strip() or "(no text — attachment/embed)")[:1500]
        return (f"\n\n>>> They REPLIED to this specific message to point you at it — "
                f"{who}: \"{body}\"\nThat's the context they care about; answer about it.\n")

    async def _context(self, message: discord.Message) -> str:
        ref_block = await self._referenced(message)
        lines: list[str] = []
        try:
            async for msg in message.channel.history(limit=config.CHAT_CONTEXT_MESSAGES, before=message):
                if not msg.content.strip():
                    continue
                speaker = "Zafven" if msg.author.id == self.bot.user.id else msg.author.display_name
                lines.append(f"{speaker}: {msg.content}")
        except discord.HTTPException:
            pass
        lines.reverse()
        lines.append(f"{message.author.display_name}: {message.content}")
        convo = "\n".join(lines)[:8000]
        return (f"This is the recent chat in #{message.channel.name}.{ref_block}\n"
                f"Reply as Zafven to the last message, in character and in context:\n\n{convo}\n\nZafven:")

    @app_commands.command(name="memory", description="See what Zafven remembers about you.")
    @app_commands.guild_only()
    async def memory(self, interaction: discord.Interaction) -> None:
        notes = await chat_memory.get_notes(interaction.guild, interaction.user.id)
        if not notes:
            await interaction.response.send_message(
                "I don't have any notes on you yet — talk to me a bit!", ephemeral=True)
            return
        body = "\n".join(f"• {n}" for n in notes)
        embed = discord.Embed(title="🧠 What I remember about you", description=body,
                              color=discord.Color.purple())
        embed.set_footer(text="Only things you told me in chat. Use /forget to wipe it.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="forget", description="Make Zafven forget what she remembers about you.")
    @app_commands.guild_only()
    async def forget(self, interaction: discord.Interaction) -> None:
        cleared = await chat_memory.clear(interaction.guild, interaction.user.id)
        msg = "Done — I've wiped my notes about you. 🧹" if cleared else "I didn't have any notes on you."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="feelings", description="See how Zafven currently feels about you.")
    @app_commands.guild_only()
    async def feelings(self, interaction: discord.Interaction) -> None:
        import time
        key = (interaction.guild.id, interaction.user.id)
        state = self._moods.get(key)
        if state:
            emotions.decay(state, state.get("_ts", time.time()), time.time())
        text = emotions.summary(state) if state else emotions.summary(emotions.new_state())
        await interaction.response.send_message(f"How I feel about you right now: **{text}**", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
