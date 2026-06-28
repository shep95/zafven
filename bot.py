"""zafven — an esoteric reading + server-management Discord bot.

Readings (Vedic, numerology, Chinese zodiac, outlook, vibe) are computed
deterministically in code and narrated by the Gemini LLM through a single
ModelGateway. Gemini is required, and reading commands are paywalled behind a
premium role / Discord subscription. Server features (join/leave logging,
inactive cleanup) need no LLM.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

import config
from core import premium
from core.model_gateway import ModelGateway

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("zafven")

INITIAL_COGS = [
    "cogs.astrology_cog",
    "cogs.numerology_cog",
    "cogs.zodiac_cog",
    "cogs.predict_cog",
    "cogs.vibe_cog",
    "cogs.logging_cog",
    "cogs.moderation_cog",
    "cogs.help_cog",
]


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    return intents


class Zafven(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=build_intents(), help_command=None)
        self.gateway = ModelGateway()

    async def setup_hook(self) -> None:
        await self.gateway.start()
        self.tree.on_error = self.on_app_command_error
        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:  # noqa: BLE001
                log.exception("Failed to load %s", ext)

        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally (may take up to 1h)", len(synced))

    async def on_ready(self) -> None:
        log.info("zafven online as %s (id=%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game(name="/help • reading the patterns"))

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: discord.app_commands.AppCommandError) -> None:
        if isinstance(error, premium.PremiumRequired):
            text, view = premium.build_upsell(interaction)
            await self._respond(interaction, text, view)
            return
        if isinstance(error, discord.app_commands.MissingPermissions):
            await self._respond(interaction, "You don't have permission to use this command.")
            return
        log.exception("Unhandled app-command error", exc_info=error)
        await self._respond(interaction, f"Something went wrong: `{error}`")

    @staticmethod
    async def _respond(interaction: discord.Interaction, content: str,
                       view: discord.ui.View | None = None) -> None:
        kwargs = {"ephemeral": True}
        if view is not None:
            kwargs["view"] = view
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, **kwargs)
            else:
                await interaction.response.send_message(content, **kwargs)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await self.gateway.close()
        await super().close()


async def main() -> None:
    problems = config.validate()
    if problems:
        raise SystemExit("Configuration errors:\n  - " + "\n  - ".join(problems)
                         + "\nCopy .env.example to .env (or set Railway Variables) and fill them in.")
    async with Zafven() as bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
