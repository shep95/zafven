"""Current command directory and application-owner command refresh."""
import discord
from discord import app_commands
from discord.ext import commands

from core.command_directory import send_directory


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Browse Zafven's current commands and options.")
    @app_commands.describe(page="Command-list page; defaults to the first page.")
    async def help(self, interaction: discord.Interaction, page: int = 1):
        await send_directory(self.bot, interaction, page)

    @app_commands.command(name="commands", description="List the installed slash commands and message actions.")
    @app_commands.describe(page="Command-list page; defaults to the first page.")
    async def command_list(self, interaction: discord.Interaction, page: int = 1):
        await send_directory(self.bot, interaction, page)

    @app_commands.command(name="synccommands", description="Bot owner: publish current commands and remove stale server copies.")
    async def synccommands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send("Only the bot/application owner can refresh application commands.", ephemeral=True)
            return
        sync = self.bot.command_sync
        try:
            count = await sync.publish()
            updated = await sync.guilds(force=True)
        except (discord.DiscordException, RuntimeError) as error:
            await interaction.followup.send(
                f"Command refresh failed ({type(error).__name__}). Check the bot logs; the refresh is not confirmed.", ephemeral=True)
            return
        failures = len(sync.guild_errors)
        await interaction.followup.send(
            f"Published {count} global command entries. Refreshed {updated} server command sets. "
            f"Server refresh failures: {failures}. "
            "Discord may need a short client refresh before the new menu appears.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
