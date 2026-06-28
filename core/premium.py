"""Discord paywall — gate premium commands behind a subscription.

Access is granted if ANY of these is true:
  1. The member has a configured premium role (PREMIUM_ROLES).
  2. The interaction carries a valid entitlement for PREMIUM_SKU_ID
     (Discord native app subscriptions / monetization).
  3. PREMIUM_BYPASS_ADMIN is on and the member is an admin / guild owner.

Use the `premium_only()` check on any command you want paywalled. Denials raise
`PremiumRequired`, which the global tree error handler turns into an upsell.
"""
from __future__ import annotations

import discord
from discord import app_commands

import config


class PremiumRequired(app_commands.CheckFailure):
    """Raised when a paywalled command is used without access."""


def _has_premium_role(user: discord.abc.User | discord.Member) -> bool:
    if not isinstance(user, discord.Member):
        return False
    wanted = set(config.PREMIUM_ROLES)
    return any(role.name.lower() in wanted for role in user.roles)


def _has_entitlement(interaction: discord.Interaction) -> bool:
    if config.PREMIUM_SKU_ID is None:
        return False
    entitlements = getattr(interaction, "entitlements", None) or []
    for ent in entitlements:
        if getattr(ent, "sku_id", None) == config.PREMIUM_SKU_ID:
            # Treat a present, non-expired, non-consumed entitlement as valid.
            if getattr(ent, "is_expired", lambda: False)():
                continue
            if getattr(ent, "consumed", False):
                continue
            return True
    return False


def _is_privileged_admin(user: discord.abc.User | discord.Member) -> bool:
    if not config.PREMIUM_BYPASS_ADMIN or not isinstance(user, discord.Member):
        return False
    if user.guild and user.id == user.guild.owner_id:
        return True
    perms = user.guild_permissions
    return perms.administrator or perms.manage_guild


def has_access(interaction: discord.Interaction) -> bool:
    user = interaction.user
    return (
        _is_privileged_admin(user)
        or _has_premium_role(user)
        or _has_entitlement(interaction)
    )


def premium_only():
    """Decorator: restrict an app command to premium members."""
    def predicate(interaction: discord.Interaction) -> bool:
        if has_access(interaction):
            return True
        raise PremiumRequired()
    return app_commands.check(predicate)


def build_upsell(interaction: discord.Interaction) -> tuple[str, discord.ui.View | None]:
    """The message shown when a non-premium member hits a paywalled command."""
    lines = [
        "🔒 **This is a premium command.**",
        "zafven's readings are for subscribers only.",
    ]
    view: discord.ui.View | None = None

    if config.PREMIUM_SKU_ID is not None:
        view = discord.ui.View()
        try:
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.premium, sku_id=config.PREMIUM_SKU_ID))
        except Exception:  # noqa: BLE001 — older discord.py without premium buttons
            view = None
    if config.SUBSCRIBE_URL:
        view = view or discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Subscribe", style=discord.ButtonStyle.link, url=config.SUBSCRIBE_URL))
    if config.PREMIUM_ROLES:
        lines.append(f"Ask a server admin for the **{config.PREMIUM_ROLES[0].title()}** role, "
                     "or subscribe below.")

    return "\n".join(lines), view
