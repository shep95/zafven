"""/help - lists zafven's commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="What can zafven do?")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="zafven - commands", color=discord.Color.dark_purple())
        embed.add_field(name="Public bot & Houseofasher", value=(
            "`/invitebot` / `/publicstatus` - public installation\n"
            "`/houseofasher [private]` - Houseofasher invite; optional requested DM\n"
            "`/houseofasher_updates <enabled>` - choose future promotional DMs\n"
            "`/promotion_setup` / `/promote_houseofasher` - approved server posts\n"
            "`/owner_role_access` / `/owner_role` - server-approved bot-owner role control"), inline=False)
        embed.add_field(
            name="Core",
            value=("`/ask <question>` - ask Zafven anything\n"
                   "`/vibe [share]` - a playful read of your own chat style\n"
                   "`/imagine <image> [question]` - describe an uploaded image\n"
                   "`/quote [text] [image] [message_link]` - quote card with a profile picture; or right-click → Quote this message\n"
                   "Mention Bible references like `John 3:16` and Zafven replies with exact verses "
                   "from configured Bible translations."),
            inline=False)
        embed.add_field(
            name="Tools",
            value=("`/research <topic>` - live web research briefing\n"
                   "`/synthesize <question> [domains]` - cross-domain research\n"
                   "`/council <question> [constraints]` - compare candidate answers and ship the best one\n"
                   "`/youtube <query>` - find YouTube videos\n"
                   "`/learn <topic|youtube link>` - post a knowledge report to #knowledge\n"
                   "`/grab <link>` - pull an image/video from a link and post it here\n"
                   "`/tldr [count]` - summarize recent messages here\n"
                   "`/askdoc <pdf> <question>` - ask a question about a PDF\n"
                   "`/audit <file>` - security + quality audit of code/.zip\n"
                   "`/forge <spec> [language]` - generate a design and code"),
            inline=False)
        embed.add_field(
            name="Just talk to her",
            value=("Mention Zafven or reply to her to ask questions, look things up, joke, and banter.\n"
                   "When she uses messages from other readable channels, she quotes the channel and sender.\n"
                   "She remembers what you tell her. `/memory` shows it, `/forget` wipes it.\n"
                   "`/adapt [style] [banter:off|light|troll]` tunes your replies; `/remember <area> <text>` saves personal notes.\n"
                   "`/feelings` shows her current mood toward you. `/culture view` shows server vibe.\n"
                   "`/teach <topic> <fact>`, `/taught`, and `/unlearn` manage learned server facts.\n"
                   "Admins can tune style with `/persona set` and add custom knowledge with `/brain add`."),
            inline=False)
        embed.add_field(name="Asher-inspired methods", value=(
            "`/asher_learn` - enable learning from Asher's public messages\n"
            "`/asher_status` / `/asher_correct` / `/asher_pause` / `/asher_reset`\n"
            "Managed by Asher or the bot owner. Learns provisional methods, not private thoughts."), inline=False)
        embed.add_field(
            name="Voice",
            value=("`/voicebots` - voice capacity and helper bot invite links.\n"
                   "`/vc join` - bring her into your voice channel; she can speak replies aloud.\n"
                   "`/say <text>` / `/vc speak <on/off>` / `/vc leave`"),
            inline=False)
        embed.add_field(
            name="Music",
            value=("`/play <link or search>` - join your VC and play music from YouTube\n"
                   "`/playnext <link>` - jump the line and play a song next\n"
                   "`/restartmusic` - restart the current song\n"
                   "`/musicfreq <0|4-8>` - optional low-frequency tremolo for future songs\n"
                   "`/defaultmusic add|list|remove|clear|start` - shared server default playlist\n"
                   "`/playlist add|list|remove|clear|start|share|accept|reject` - personal playlists\n"
                   "`/loop track|queue|off` / `/queue` / `/shuffle` / `/remove <n>` / `/clear`\n"
                   "`/nowplaying` / `/skip` / `/pause` / `/resume` / `/volume <0-200>` / `/stop`\n"
                   "`/247 on` - keep Zafven in the channel and rejoin after restart"),
            inline=False)
        embed.add_field(
            name="Community & moderation",
            value=("`/rank [member]` / `/leaderboard` - XP & levels\n"
                   "`/invite` - personal invite link · `/invites [member]` · `/invitelb` - "
                   "referral leaderboard\n"
                   "`/capsule <message> <deliver_on> [public]` - send a message to the future\n"
                   "`/mood` - aggregate read of the server's current vibe\n"
                   "`/cipher` (mod) / `/solve <answer>` - cipher puzzle events\n"
                   "`/kick_inactive [days] [dry_run] [message]` - preview/remove inactive members\n"
                   "`/report <message_link> [reason]` - escalate a message to mods\n"
                   "`/backup_history [limit]` / `/backup_status` - private message archive (admins)\n"
                   "`/discover_members` / `/reinvite` / `/reinvite_status` / `/reinvite_cancel` - batch invitations (admins)\n"
                   "Welcome cards, deleted-message logs, and manual moderator reports are available."),
            inline=False)
        embed.set_footer(text="zafven")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
