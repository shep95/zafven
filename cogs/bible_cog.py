"""Reply with exact Bible passages when users mention verse references."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from core import bible

log = logging.getLogger("zafven.bible")


class BibleCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not config.BIBLE_REPLY_ENABLED:
            return
        if message.author.bot or message.guild is None or not message.content.strip():
            return
        if not message.channel.permissions_for(message.guild.me).send_messages:
            return

        refs = bible.find_references(message.content, limit=config.BIBLE_MAX_REFERENCES)
        if not refs:
            return

        for ref in refs:
            try:
                passages = await bible.fetch_passages(ref)
            except Exception as exc:  # noqa: BLE001 - lookup must not break message listeners
                log.warning("Bible lookup failed for %s: %s", ref, exc)
                continue
            if not passages:
                continue

            embed = discord.Embed(
                title=passages[0].reference,
                color=discord.Color.dark_gold(),
            )
            for passage in passages[:config.BIBLE_MAX_TRANSLATIONS]:
                value = passage.text[:1024]
                embed.add_field(name=passage.translation[:256], value=value, inline=False)
            embed.set_footer(text="Bible text from public-domain/open translations")
            try:
                await message.reply(embed=embed, mention_author=False)
            except discord.HTTPException:
                return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BibleCog(bot))
