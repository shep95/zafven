"""Show configured voice-account capacity and helper installation links."""
import discord
from discord import app_commands
from discord.ext import commands

from core.public_bot import installation_url
from core.voice_pool import VoicePool


class VoicePoolCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="voicebots", description="Show voice helpers, active rooms, and helper invite links.")
    @app_commands.guild_only()
    async def voicebots(self, interaction: discord.Interaction):
        pool = getattr(self.bot, "voice_pool", None)
        bots = pool.bots if isinstance(pool, VoicePool) else [self.bot]
        lines = []
        for index, bot in enumerate(bots, 1):
            if bot.user is None:
                lines.append(f"Account {index}: starting or offline.")
                continue
            ready = pool.ready(bot, interaction.guild.id) if isinstance(pool, VoicePool) else bot.is_ready()
            guild = bot.get_guild(interaction.guild.id) if ready else None
            vc = guild.voice_client if guild else None
            state = "available here" if guild else "not ready here or not in this server"
            if vc and vc.is_connected():
                source = interaction.guild.get_channel(vc.channel.id)
                visible = source and source.permissions_for(interaction.user).view_channel
                state = f"connected to {discord.utils.escape_markdown(vc.channel.name)}" if visible else "busy in another room"
            lines.append(f"**{discord.utils.escape_markdown(bot.user.name)}**: {state}\n{installation_url(bot.application_id or bot.user.id)}")
        lines.append("Each account supports one room per server. Add distinct bot tokens in VOICE_BOT_TOKENS for more capacity.")
        pages = [""]
        for line in lines:
            if len(pages[-1]) + len(line) + 2 > 1900:
                pages.append("")
            pages[-1] += line + "\n\n"
        await interaction.response.send_message(pages[0], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        for page in pages[1:]:
            await interaction.followup.send(page, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(VoicePoolCog(bot))
