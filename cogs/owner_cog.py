"""`/owner` — controls only the bot's creator (config.OWNER_ID) can use.

Lets the owner manage the bot itself from anywhere: see the servers it's in, make
it leave one, get its invite link to add it to a new server, and manage the global
protect-list (accounts the bot's own auto-moderation never touches).

Scope note (honest): these govern the BOT. They do not and cannot override another
server's own admins or Discord's native moderation — see core/owner.py.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import owner, store as store_mod

log = logging.getLogger("zafven.owner_cog")


async def _home_store(bot: commands.Bot):
    """The store that holds global owner data: GLOBAL_DATA_GUILD, else GUILD_ID,
    else the first guild the bot is in."""
    gid = getattr(config, "GLOBAL_DATA_GUILD", 0) or config.GUILD_ID or 0
    guild = bot.get_guild(int(gid)) if gid else None
    if guild is None and bot.guilds:
        guild = bot.guilds[0]
    if guild is None:
        return None
    return await store_mod.get_store(guild)


class OwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            s = await _home_store(self.bot)
            if s is not None:
                await owner.load(s)
        except Exception:  # noqa: BLE001
            log.exception("failed to load owner protect-list")

    def _deny_if_not_owner(self, interaction: discord.Interaction) -> bool:
        return not owner.is_owner(interaction.user.id)

    owner_grp = app_commands.Group(name="owner", description="Bot-owner-only controls.")

    @owner_grp.command(name="servers", description="List the servers the bot is in.")
    async def servers(self, interaction: discord.Interaction) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        guilds = sorted(self.bot.guilds, key=lambda g: -(g.member_count or 0))
        lines = [f"• **{g.name}** — `{g.id}` ({g.member_count} members)" for g in guilds[:25]]
        body = "\n".join(lines) or "_(not in any servers)_"
        await interaction.response.send_message(
            f"🛰️ in **{len(self.bot.guilds)}** server(s):\n{body}", ephemeral=True)

    @owner_grp.command(name="leave", description="Make the bot leave a server by id.")
    @app_commands.describe(guild_id="The server id to leave.")
    async def leave(self, interaction: discord.Interaction, guild_id: str) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        try:
            guild = self.bot.get_guild(int(guild_id))
        except ValueError:
            guild = None
        if guild is None:
            await interaction.response.send_message("i'm not in a server with that id.", ephemeral=True)
            return
        name = guild.name
        await guild.leave()
        await interaction.response.send_message(f"👋 left **{name}** (`{guild_id}`).", ephemeral=True)

    @owner_grp.command(name="invite", description="Get the link to add the bot to another server.")
    async def invite(self, interaction: discord.Interaction) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        if self.bot.user is None:
            await interaction.response.send_message("not ready yet — try again in a moment.", ephemeral=True)
            return
        # A broad-but-standard permission set for the bot's features (moderation,
        # messages, voice). Whoever adds the bot must have Manage Server there.
        perms = discord.Permissions(
            manage_messages=True, moderate_members=True, kick_members=True, ban_members=True,
            send_messages=True, embed_links=True, attach_files=True, read_message_history=True,
            connect=True, speak=True, manage_channels=True, create_instant_invite=True,
            view_channel=True, add_reactions=True)
        url = discord.utils.oauth_url(
            self.bot.user.id, permissions=perms, scopes=("bot", "applications.commands"))
        await interaction.response.send_message(
            f"🔗 add zafven to a server (you need **Manage Server** there):\n{url}", ephemeral=True)

    # ── protect-list (bot's own auto-moderation exemption) ────────────────
    protect = app_commands.Group(name="protect", description="Accounts the bot's auto-moderation never touches.", parent=owner_grp)

    @protect.command(name="add", description="Protect an account from the bot's auto-moderation (global).")
    @app_commands.describe(user_id="The account id to protect.")
    async def protect_add(self, interaction: discord.Interaction, user_id: str) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("that's not a valid account id.", ephemeral=True)
            return
        s = await _home_store(self.bot)
        if s is None:
            await interaction.response.send_message("no data store available yet.", ephemeral=True)
            return
        added = await owner.add_protected(s, uid)
        msg = (f"🛡️ `{uid}` is now protected — my auto-moderation won't action them in any server. "
               "(this governs **my** actions only; it can't stop a server's own admins.)"
               if added else f"`{uid}` was already protected.")
        await interaction.response.send_message(msg, ephemeral=True)

    @protect.command(name="remove", description="Stop protecting an account.")
    @app_commands.describe(user_id="The account id to unprotect.")
    async def protect_remove(self, interaction: discord.Interaction, user_id: str) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("that's not a valid account id.", ephemeral=True)
            return
        s = await _home_store(self.bot)
        if s is None:
            await interaction.response.send_message("no data store available yet.", ephemeral=True)
            return
        removed = await owner.remove_protected(s, uid)
        await interaction.response.send_message(
            f"removed `{uid}` from the protect-list." if removed else f"`{uid}` wasn't protected.",
            ephemeral=True)

    @protect.command(name="list", description="Show the protected accounts.")
    async def protect_list(self, interaction: discord.Interaction) -> None:
        if self._deny_if_not_owner(interaction):
            await interaction.response.send_message("owner only.", ephemeral=True)
            return
        ids = owner.protected_ids()
        body = "\n".join(f"• `{i}`" for i in ids) or "_(none — only you are implicitly protected)_"
        await interaction.response.send_message(f"🛡️ protected accounts:\n{body}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OwnerCog(bot))
