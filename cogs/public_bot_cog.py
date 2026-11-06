"""Public install link, requested Houseofasher promotion, and delegated owner roles."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.public_bot import settings, installation_url, personalized_invitation


class PublicBotCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = settings

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            return
        try:
            await channel.send(
                "Zafven is ready. Use /help and /privacy for features and data handling. "
                "Public promotions are off until /promotion_setup approves a channel. "
                "Bot-owner role delegation is off until /owner_role_access approves individual roles. "
                "This server controls permissions and can remove the bot.",
                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @app_commands.command(name="privacy", description="See how Zafven stores messages and personal memory.")
    async def privacy(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Zafven can store received server messages/metadata in local storage and private archive channels. "
            "Personal preferences and recent exchanges are stored per server/user and mirrored to hidden channels "
            "visible to the bot and server administrators. Requested AI features send context to Gemini. "
            "/memory inspects your active memory; /forget resets it, but does not delete general message archives. "
            "Server administrators control channel access. Promotional DMs require your request or opt-in; "
            "/houseofasher_updates enabled:False revokes future promotional DMs.", ephemeral=True)

    @app_commands.command(name="invitebot", description="Get Zafven's public server-install link.")
    async def invitebot(self, interaction: discord.Interaction):
        app_id = self.bot.application_id or self.bot.user.id
        await interaction.response.send_message(
            "Invite Zafven to a server you can manage:\n" + installation_url(app_id), ephemeral=True)

    @app_commands.command(name="publicstatus", description="Check public-install readiness and platform permissions.")
    async def publicstatus(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        app = await self.bot.application_info()
        await interaction.followup.send(
            f"Public Bot enabled on Discord: {app.bot_public}. "
            f"Global commands configured: {config.GUILD_ID is None}. "
            "Servers control granted permissions and can remove the bot. "
            "Use /invitebot for the install URL.", ephemeral=True)

    @app_commands.command(name="houseofasher", description="Get the Houseofasher invite, optionally as a personalized DM.")
    @app_commands.describe(private="True requests one personalized DM; False shows the link here privately.")
    async def houseofasher(self, interaction: discord.Interaction, private: bool = False):
        await interaction.response.defer(ephemeral=True)
        if private:
            try:
                await interaction.user.send(personalized_invitation(interaction.user),
                                            allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                await interaction.followup.send("I couldn't DM you. Here's the invite: " + config.HOUSEOFASHER_INVITE_URL,
                                                ephemeral=True)
                return
            await interaction.followup.send("Your personalized invite was sent. This does not subscribe you to future DMs.", ephemeral=True)
        else:
            await interaction.followup.send("Join #houseofasher: " + config.HOUSEOFASHER_INVITE_URL, ephemeral=True)

    @app_commands.command(name="houseofasher_updates", description="Opt in or out of future Houseofasher invitation DMs.")
    async def houseofasher_updates(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        await self.settings.consent(interaction.user.id, enabled)
        await interaction.followup.send("Future Houseofasher invitation DMs: " + ("on" if enabled else "off") +
                                        ". Change this setting anytime.", ephemeral=True)

    @app_commands.command(name="promotion_setup", description="Approve or disable a channel for Houseofasher promotional posts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def promotion_setup(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        await interaction.response.defer(ephemeral=True)
        if channel and channel.guild.id != interaction.guild.id:
            await interaction.followup.send("Choose a channel in this server.", ephemeral=True)
            return
        await self.settings.change(interaction.guild.id,
                                   lambda s: s.update(promotion_channel=channel.id if channel else None))
        await interaction.followup.send("Promotion channel approved." if channel else "Server promotional posts disabled.", ephemeral=True)

    @app_commands.command(name="promote_houseofasher", description="Post the Houseofasher invite in the server-approved channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def promote_houseofasher(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        state = await self.settings.get(interaction.guild.id)
        channel = interaction.guild.get_channel(state.get("promotion_channel") or 0)
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("First approve a channel with /promotion_setup.", ephemeral=True)
            return
        embed = discord.Embed(title="#houseofasher", description="Come meet the Houseofasher community.",
                              color=discord.Color.purple(), url=config.HOUSEOFASHER_INVITE_URL)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join Houseofasher", url=config.HOUSEOFASHER_INVITE_URL))
        try:
            await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await interaction.followup.send("I couldn't post in the approved channel. Check its permissions.", ephemeral=True)
            return
        await interaction.followup.send("Posted in the approved channel.", ephemeral=True)

    @app_commands.command(name="owner_role_access", description="Approve a role the bot owner may assign, or revoke that approval.")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def owner_role_access(self, interaction: discord.Interaction, role: discord.Role, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if role.guild.id != interaction.guild.id or role.is_default() or role.managed:
            await interaction.followup.send("Choose an ordinary role in this server.", ephemeral=True)
            return
        if interaction.user.id != interaction.guild.owner_id and role >= interaction.user.top_role:
            await interaction.followup.send("You can only delegate roles below your own highest role.", ephemeral=True)
            return
        def update(state):
            roles = set(state.get("owner_roles", []))
            (roles.add if enabled else roles.discard)(role.id)
            state["owner_roles"] = sorted(roles)
        await self.settings.change(interaction.guild.id, update)
        await interaction.followup.send("Bot-owner assignment approved for this role." if enabled else "Role approval revoked.", ephemeral=True)

    @app_commands.command(name="owner_role", description="Bot owner: assign or remove a server-approved role.")
    @app_commands.guild_only()
    async def owner_role(self, interaction: discord.Interaction, member: discord.Member,
                         role: discord.Role, grant: bool = True):
        await interaction.response.defer(ephemeral=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.followup.send("Only the bot application's owner can use this command.", ephemeral=True)
            return
        guild = interaction.guild
        state = await self.settings.get(guild.id)
        if role.id not in state.get("owner_roles", []):
            await interaction.followup.send("This server has not approved bot-owner assignment of that role.", ephemeral=True)
            return
        if role.guild.id != guild.id or member.guild.id != guild.id or role.is_default() or role.managed:
            await interaction.followup.send("Choose an ordinary role and member in this server.", ephemeral=True)
            return
        if not guild.me.guild_permissions.manage_roles or role >= guild.me.top_role:
            await interaction.followup.send("I need Manage Roles and a highest role above the selected role.", ephemeral=True)
            return
        try:
            action = member.add_roles if grant else member.remove_roles
            await action(role, reason=f"Approved bot-owner role action by {interaction.user.id}")
        except discord.HTTPException:
            await interaction.followup.send("Discord rejected the role action. Check permissions and hierarchy.", ephemeral=True)
            return
        await interaction.followup.send("Role assigned." if grant else "Role removed.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PublicBotCog(bot))
