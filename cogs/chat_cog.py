"""Zafven's live chat personality — she replies when @mentioned or replied to.

Keeps it natural: pulls the recent channel context, answers in character via the
companion brain, and threads the reply. Cooldown per channel to avoid spam/cost.
Ambient (unprompted) replies are off by default (CHAT_AMBIENT_CHANCE=0).
"""
from __future__ import annotations

import logging
import random
import time

import discord
from discord.ext import commands

import config
from core.brain_loader import load as load_brain
from core.model_gateway import GatewayError

log = logging.getLogger("zafven.chat")


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cooldown: dict[int, float] = {}

    def _system(self) -> str:
        return load_brain("companion")

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

        perms = message.channel.permissions_for(message.guild.me)
        if not perms.send_messages:
            return

        try:
            async with message.channel.typing():
                transcript = await self._context(message)
                reply = await self.bot.gateway.narrate(  # type: ignore[attr-defined]
                    self._system(), transcript, web_search=False, max_tokens=300)
        except GatewayError as exc:
            log.warning("chat reply failed: %s", exc)
            return

        try:
            await message.reply(reply[:2000], mention_author=False)
        except discord.HTTPException:
            try:
                await message.channel.send(reply[:2000])
            except discord.HTTPException:
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
