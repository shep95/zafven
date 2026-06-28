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
from core import chat_memory
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
        self._cooldown: dict[int, float] = {}

    def _system(self, display_name: str, notes: list[str]) -> str:
        base = load_brain("companion")
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
        if not addressed and random.random() >= config.CHAT_AMBIENT_CHANCE:
            return

        now = time.time()
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
            async with message.channel.typing():
                transcript = await self._context(message)
                raw = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                    self._system(message.author.display_name, notes), transcript,
                    web_search=None, max_tokens=600)
        except GatewayError as exc:
            log.warning("chat reply failed: %s", exc)
            return

        remembered = REMEMBER_RE.findall(raw)
        visible = REMEMBER_RE.sub("", raw).strip() or "…"

        try:
            await message.reply(visible[:2000], mention_author=False)
        except discord.HTTPException:
            try:
                await message.channel.send(visible[:2000])
            except discord.HTTPException:
                pass

        for note in remembered:
            try:
                await chat_memory.add_note(message.guild, message.author.id, note)
            except Exception:  # noqa: BLE001
                pass

    async def _context(self, message: discord.Message) -> str:
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
        return (f"This is the recent chat in #{message.channel.name}. "
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
