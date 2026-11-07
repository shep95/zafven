"""Known-member discovery and a persistent, administrator-started reinvite batch."""
from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.community_db import database
from core.welcome import render_invitation
from core.invitation_delivery import dm_failure
from core.public_bot import settings as public_settings

log = logging.getLogger("zafven.reinvite")
CAMPAIGN = "houseofasher-relaunch-v1"


class ReinviteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = database
        self.public_settings = public_settings
        self._discovery: dict[int, asyncio.Task] = {}
        self._queue_lock = asyncio.Lock()
        self._inflight = None
        self.deliver.start()

    def cog_unload(self):
        self.deliver.cancel()
        for job in self._discovery.values():
            job.cancel()

    async def _remember(self, guild, user, present, source):
        if not user.bot:
            await self.db.remember(guild.id, user.id, str(user), present=present, source=source)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            for member in guild.members:
                await self._remember(guild, member, True, "current")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self._remember(member.guild, member, True, "joined")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self._remember(member.guild, member, False, "departed")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self._remember(guild, user, False, "banned")

    @app_commands.command(name="discover_members", description="Discover known former members from kick logs and member logs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def discover_members(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        if gid in self._discovery:
            await interaction.response.send_message("A member discovery scan is already running.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Member discovery started. /reinvite previews the current directory. "
            "Use /backup_history too to discover former message authors.", ephemeral=True)
        self._discovery[gid] = asyncio.create_task(self._discover(interaction.guild))

    async def _discover(self, guild):
        try:
            for member in guild.members:
                await self._remember(guild, member, True, "current")
            if guild.me.guild_permissions.view_audit_log:
                async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.kick):
                    user = entry.target
                    if user is not None and not getattr(user, "bot", False):
                        await self.db.remember(guild.id, user.id, str(user),
                            present=guild.get_member(user.id) is not None, source="kick-log")
            # The existing member-log cog writes the departed member ID in its footer.
            channel = discord.utils.get(guild.text_channels, name=config.MEMBER_LOG_CHANNEL)
            if channel and channel.permissions_for(guild.me).read_message_history:
                async for message in channel.history(limit=None):
                    if message.author.id != self.bot.user.id:
                        continue
                    for embed in message.embeds:
                        match = re.fullmatch(r"ID: (\d{15,22})", embed.footer.text or "")
                        if match:
                            uid = int(match[1])
                            await self.db.remember(guild.id, uid, f"User {uid}",
                                present=guild.get_member(uid) is not None, source="member-log")
        except discord.HTTPException:
            log.exception("Member discovery incomplete for %s", guild.id)
        except Exception:
            log.exception("Member discovery failed for %s", guild.id)
        finally:
            self._discovery.pop(guild.id, None)

    async def _targets(self, guild, audience):
        # Fresh current-member snapshot avoids relying on stale stored presence.
        current = {member.id for member in guild.members if not member.bot}
        for member in guild.members:
            await self._remember(guild, member, True, "current")
        known = {int(row["user_id"]) for row in await self.db.members(guild.id)}
        if config.PUBLIC_BOT_MODE:
            consenting = await self.public_settings.subscribers()
            known &= consenting
            current &= consenting
        banned = set()
        if guild.me.guild_permissions.ban_members:
            async for entry in guild.bans(limit=None):
                banned.add(entry.user.id)
        if audience == "current":
            return sorted(current - banned)
        if audience == "former":
            return sorted(known - current - banned)
        return sorted((known | current) - banned)

    async def _link(self, guild):
        channels = ([guild.system_channel] if guild.system_channel else []) + list(guild.text_channels)
        for channel in channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                invite = await channel.create_invite(max_age=0, max_uses=0, unique=True,
                                                     reason="Houseofasher reinvitation campaign")
                return invite.url
        return None

    def _home_problem(self, guild):
        if not config.PUBLIC_BOT_MODE:
            return None
        if not config.HOUSEOFASHER_GUILD_ID:
            return ("Batch invitations are not configured. The bot owner must set HOUSEOFASHER_GUILD_ID "
                    "to the Houseofasher server ID in the deployment and restart the bot.")
        if guild.id != config.HOUSEOFASHER_GUILD_ID:
            return "Public batch invitations run only inside the configured Houseofasher server. Run /reinvite there."
        return None

    @app_commands.command(name="reinvite", description="Preview or queue the invitation to current and known former members.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(audience=[app_commands.Choice(name=n, value=n) for n in ("all", "current", "former")])
    @app_commands.describe(dry_run="True previews only; False queues DMs.",
                           campaign="Keep the same name on reruns to avoid resending successful invitations.")
    async def reinvite(self, interaction: discord.Interaction, audience: str = "all",
                       dry_run: bool = True, campaign: str = CAMPAIGN):
        await interaction.response.defer(ephemeral=True)
        if problem := self._home_problem(interaction.guild):
            await interaction.followup.send(
                problem + " No DMs were queued. Recipients opt in with /houseofasher_updates. "
                "For a one-time requested invite, use /houseofasher private:True.", ephemeral=True)
            return
        campaign = campaign.strip()
        if not campaign or len(campaign) > 100:
            await interaction.followup.send("Campaign name must be 1–100 characters.", ephemeral=True)
            return
        if interaction.guild.id in self._discovery or (
            (backup := self.bot.get_cog("BackupCog")) is not None and interaction.guild.id in backup._jobs
        ):
            await interaction.followup.send("Discovery/history is still running; wait before selecting recipients.", ephemeral=True)
            return
        async with self._queue_lock:
            targets = await self._targets(interaction.guild, audience)
            known = {int(row["user_id"]) for row in await self.db.members(interaction.guild.id)}
            known.update(member.id for member in interaction.guild.members if not member.bot)
            summary = f"Known members: {len(known)}. Eligible for {audience}: {len(targets)}. "
            if config.PUBLIC_BOT_MODE:
                subscribed = known & await self.public_settings.subscribers()
                summary += f"Known members opted in to invitation DMs: {len(subscribed)}. "
            if not targets:
                await interaction.followup.send(
                    summary + "No eligible recipients, so no DMs were queued. "
                    + ("Users choose future invitation DMs with /houseofasher_updates enabled:True. " if config.PUBLIC_BOT_MODE else "")
                    + "Use /discover_members or /backup_history to expand the known-member directory. "
                    "For a one-time invitation to yourself, use /houseofasher private:True.", ephemeral=True)
                return
            if dry_run:
                state = await self.db.campaign_status(interaction.guild.id, campaign)
                await interaction.followup.send(
                    f"Preview only — {summary}Campaign: {campaign}. "
                    f"Existing deliveries: {state or 'none'}. No DMs sent. "
                    "This preview does not create a delivery campaign. Use /reinvite dry_run:False with the same campaign name to queue. "
                    "Historical membership may be incomplete.", ephemeral=True)
                return
            link = config.HOUSEOFASHER_INVITE_URL if config.PUBLIC_BOT_MODE else await self._link(interaction.guild)
            if not link:
                await interaction.followup.send("I need Create Invite in a server channel. No DMs queued.", ephemeral=True)
                return
            body = render_invitation(link)
            if len(body) > 2000:
                await interaction.followup.send("Invitation exceeds Discord's 2,000-character message limit. No DMs queued.", ephemeral=True)
                return
            added = await self.db.enqueue(interaction.guild.id, campaign, targets, body)
        if not added:
            await interaction.followup.send(
                "No new recipients were added: eligible recipients already have entries in this campaign. "
                "Use /reinvite_status and select " + discord.utils.escape_markdown(campaign) +
                " to see sent, failed, or pending deliveries. Existing attempts are not automatically resent.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        await interaction.followup.send(
            f"Queued {added} new recipient(s) for {campaign}. Existing campaign recipients were not added twice. "
            "Use /reinvite_status or /reinvite_cancel.", ephemeral=True)

    @app_commands.command(name="reinvite_status", description="See batch invitation delivery counts.")
    @app_commands.describe(campaign="Choose an existing batch; omit to show the most recently queued campaign.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reinvite_status(self, interaction: discord.Interaction, campaign: str | None = None):
        await interaction.response.defer(ephemeral=True)
        campaigns = await self.db.campaign_names(interaction.guild.id, limit=5)
        if campaign is None:
            campaign = campaigns[0] if campaigns else None
        else:
            campaign = campaign.strip()
            if not campaign or len(campaign) > 100:
                await interaction.followup.send("Campaign name must be 1–100 characters.", ephemeral=True)
                return
        state = await self.db.campaign_status(interaction.guild.id, campaign) if campaign else {}
        if not state:
            message = ("No delivery records found" + (" for that campaign" if campaign else " in this server") + ". "
                "/reinvite defaults to a preview, which does not send or queue DMs. "
                "To queue eligible recipients, run /reinvite dry_run:False and set the campaign name. "
                "Use the campaign suggestions in /reinvite_status to select an existing batch.")
            if campaigns:
                message += "\nQueued campaigns: " + ", ".join(discord.utils.escape_markdown(name) for name in campaigns)
            if problem := self._home_problem(interaction.guild):
                message += "\n" + problem
        else:
            message = "Campaign: " + discord.utils.escape_markdown(campaign) + "\n"
            labels = {"pending": "Queued", "sent": "Sent", "failed": "Failed", "skipped": "Skipped", "cancelled": "Cancelled"}
            message += " · ".join(f"{label}: {state.get(key, 0)}" for key, label in labels.items())
            if state.get("sending"):
                active = int(bool(self._inflight and str(self._inflight["guild_id"]) == str(interaction.guild.id)
                                  and self._inflight["campaign"] == campaign))
                uncertain = max(0, state["sending"] - active)
                if active:
                    message += f"\nSending now: {active}."
                if uncertain:
                    message += f"\nUnconfirmed attempts: {uncertain}. These may be from an interrupted run and are not automatically resent, to avoid duplicate DMs."
            for failure in await self.db.campaign_errors(interaction.guild.id, campaign):
                reason = discord.utils.escape_markdown(failure["error"][:220]).replace("@", "＠")
                message += f"\n{failure['n']} recipient(s): {reason}"
        if interaction.guild.id in self._discovery:
            message += "\nMember discovery is still running."
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="reinvite_cancel", description="Cancel invitations that have not started sending.")
    @app_commands.describe(campaign="Choose a batch; omit to cancel pending entries in the most recently queued campaign.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def reinvite_cancel(self, interaction: discord.Interaction, campaign: str | None = None):
        await interaction.response.defer(ephemeral=True)
        if campaign is None:
            names = await self.db.campaign_names(interaction.guild.id, limit=1)
            campaign = names[0] if names else None
        if campaign is None:
            await interaction.followup.send("No queued campaigns were found in this server.", ephemeral=True)
            return
        campaign = campaign.strip()
        if not campaign or len(campaign) > 100:
            await interaction.followup.send("Campaign name must be 1–100 characters.", ephemeral=True)
            return
        count = await self.db.cancel_campaign(interaction.guild.id, campaign)
        await interaction.followup.send(
            f"Cancelled {count} pending deliveries for " + discord.utils.escape_markdown(campaign) +
            ". Already-sending messages are not cancelled and may still complete.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @reinvite.autocomplete("campaign")
    @reinvite_status.autocomplete("campaign")
    @reinvite_cancel.autocomplete("campaign")
    async def campaign_suggestions(self, interaction: discord.Interaction, current: str):
        if interaction.guild is None or not interaction.user.guild_permissions.manage_guild:
            return []
        names = await self.db.campaign_names(interaction.guild.id, search=current)
        return [app_commands.Choice(name=name, value=name) for name in names]

    @tasks.loop(seconds=2)
    async def deliver(self):
        row = None
        try:
            row = await self.db.pending_delivery()
            if row is None:
                return
            if not await self.db.claim_delivery(row):
                return  # Cancelled or claimed elsewhere between lookup and send.
            self._inflight = row
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                await self.db.delivery_status(row, "skipped", "Bot is no longer in the server")
                return
            if config.PUBLIC_BOT_MODE and (
                guild.id != config.HOUSEOFASHER_GUILD_ID
                or not await self.public_settings.subscribed(int(row["user_id"]))
            ):
                await self.db.delivery_status(row, "skipped", "Public promotion consent or home-server requirement not met")
                return
            user = self.bot.get_user(int(row["user_id"])) or await self.bot.fetch_user(int(row["user_id"]))
            if user.bot:
                await self.db.delivery_status(row, "skipped", "Bot account")
                return
            # An interrupted attempt stays 'sending' and is never blindly retried.
            try:
                await user.send(row["body"], allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                await self.db.delivery_status(row, "failed", dm_failure(exc))
            else:
                await self.db.delivery_status(row, "sent")
        except discord.HTTPException as exc:
            if row:
                await self.db.delivery_status(row, "failed", dm_failure(exc))
            log.warning("Reinvite user lookup failed: %s", exc)
        except Exception:
            log.exception("Reinvite delivery iteration failed")
        finally:
            self._inflight = None

    @deliver.before_loop
    async def before_delivery(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ReinviteCog(bot))
