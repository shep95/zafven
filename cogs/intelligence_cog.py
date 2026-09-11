"""Management surface for the Asherin intelligence layer (§39).

A Discord bot's "UI" is its slash commands, so this cog exposes the controls the
spec wants users to have — memory on/off + status, a view of pattern learning, the
model-provider/credential config, and the global-learning status/run — WITHOUT ever
exposing raw secrets or hidden chain-of-thought. It also runs the scheduled monthly
global-learning cycle.

Everything guards on `bot.intelligence` being present, so the cog is inert (not
broken) when the intelligence layer is disabled.
"""
from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("zafven.intel.cog")

_MONTH_SECONDS = 28 * 86400


class IntelligenceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        if config.INTELLIGENCE_ENABLED and config.GLOBAL_LEARNING_ENABLED and config.GLOBAL_LEARNING_AUTORUN:
            self._monthly.start()

    def cog_unload(self) -> None:
        self._monthly.cancel()

    def _intel(self):
        return getattr(self.bot, "intelligence", None)

    # ── scheduled monthly global-learning cycle (§28) ─────────────────────
    @tasks.loop(hours=24)
    async def _monthly(self) -> None:
        intel = self._intel()
        if intel is None:
            return
        try:
            gl = await intel.ensure_global(self.bot)
            if gl is None:
                return
            history = gl.manifests()
            last = history[-1]["generated_at"] if history else 0
            if time.time() - last < _MONTH_SECONDS:
                return
            manifest = await intel.run_global_cycle(self.bot)
            log.info("scheduled global cycle ran: %s", manifest)
        except Exception:  # noqa: BLE001
            log.exception("scheduled global cycle failed")

    @_monthly.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    # ── /memory ───────────────────────────────────────────────────────────
    memory = app_commands.Group(name="memory", description="Control what Zafven remembers about you.")

    @memory.command(name="status", description="See whether Zafven's memory of you is on, and what she recalls.")
    @app_commands.guild_only()
    async def memory_status(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        on = gi.memory.is_user_memory_enabled(interaction.user.id)
        items = gi.memory.user_items(interaction.user.id)
        body = "\n".join(f"• {i.text}  _({i.kind}, {i.scope})_" for i in items[-12:]) or "_(nothing yet)_"
        embed = discord.Embed(
            title="🧠 your memory",
            description=f"persistent memory: **{'on' if on else 'off'}**\n\n{body}",
            color=discord.Color.purple())
        embed.set_footer(text="/memory off stops new persistent memory · /forget wipes it")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @memory.command(name="on", description="Turn ON persistent memory of you.")
    @app_commands.guild_only()
    async def memory_on(self, interaction: discord.Interaction) -> None:
        await self._set_memory(interaction, True)

    @memory.command(name="off", description="Turn OFF persistent memory of you (nothing new is stored).")
    @app_commands.guild_only()
    async def memory_off(self, interaction: discord.Interaction) -> None:
        await self._set_memory(interaction, False)

    async def _set_memory(self, interaction: discord.Interaction, on: bool) -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        await gi.memory.set_user_memory(interaction.user.id, on)
        msg = ("persistent memory is **on** — i'll remember durable things you tell me."
               if on else
               "persistent memory is **off** — i won't store anything new about you.")
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /patterns (read-only view of pattern learning) ─────────────────────
    @app_commands.command(name="patterns", description="See the problem-solving patterns Zafven has learned here.")
    @app_commands.guild_only()
    async def patterns(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        counts = gi.registry.counts_by_status()
        applicable = [p for p in gi.registry.all() if p.is_applicable()]
        applicable.sort(key=lambda p: -p.confidence)
        lines = [f"• **{p.name}** — {p.mechanism[:120]}  _(conf {p.confidence:.2f}, {p.scope})_"
                 for p in applicable[:8]] or ["_(no proven patterns yet — they start as candidates and earn trust from outcomes)_"]
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none yet"
        embed = discord.Embed(
            title="🧩 learned patterns (this server)",
            description="\n".join(lines),
            color=discord.Color.teal())
        embed.set_footer(text=f"lifecycle → {summary}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /provider (model + credential; secrets never shown raw) ────────────
    provider = app_commands.Group(name="provider", description="Choose the AI model/provider this server uses.")

    @provider.command(name="status", description="Show the active model provider (secrets are masked).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def provider_status(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        d = gi.credentials.describe()
        caps = gi.provider.capabilities()
        if d["configured"] and config.PROVIDER_USER_KEYS_ENABLED:
            who = f"this server's own key — {d['provider']} `{d['masked']}` (model: {d['model'] or 'default'})"
        else:
            who = "zafven's built-in model"
        body = (f"active: **{who}**\n\ncapabilities: vision={caps.vision}, tools={caps.tool_calling}, "
                f"context≈{caps.context_window:,}, coding={caps.coding_suitability}")
        if not config.PROVIDER_USER_KEYS_ENABLED:
            body += "\n\n_user-supplied keys are disabled by the host (PROVIDER_USER_KEYS_ENABLED)._"
        await interaction.response.send_message(body, ephemeral=True)

    @provider.command(name="setkey", description="Use this server's own model API key (stored privately, never shown).")
    @app_commands.describe(api_key="Your provider API key", model="Optional model id (blank = default)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def provider_setkey(self, interaction: discord.Interaction, api_key: str, model: str = "") -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        if not config.PROVIDER_USER_KEYS_ENABLED:
            await interaction.response.send_message(
                "user-supplied keys are disabled by the host. ask the operator to set "
                "`PROVIDER_USER_KEYS_ENABLED=true`.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        await gi.credentials.set_credential("gemini", api_key, model)
        intel.invalidate_guild(interaction.guild.id)  # rebuild provider with the new key
        await interaction.response.send_message(
            "saved. this server now uses its own key. it's stored privately and never "
            "placed in prompts, patterns, memory, or logs. note: keys live in the bot's "
            "data channel (opt-in), which is not KMS-grade — rotate if that matters.",
            ephemeral=True)

    @provider.command(name="clearkey", description="Stop using this server's own key (revert to built-in).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def provider_clearkey(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None:
            await interaction.response.send_message("the intelligence layer is off.", ephemeral=True)
            return
        gi = await intel.for_guild(interaction.guild)
        await gi.credentials.clear_credential()
        intel.invalidate_guild(interaction.guild.id)
        await interaction.response.send_message("done — back to zafven's built-in model.", ephemeral=True)

    # ── /globallearn (cross-guild pattern evolution) ───────────────────────
    globallearn = app_commands.Group(name="globallearn", description="Cross-server pattern learning (abstracted, private).")

    @globallearn.command(name="status", description="Show global-learning state: quarantine, layers, last cycle.")
    @app_commands.guild_only()
    async def globallearn_status(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None or not config.GLOBAL_LEARNING_ENABLED:
            await interaction.response.send_message("global learning is off.", ephemeral=True)
            return
        gl = await intel.ensure_global(self.bot)
        if gl is None:
            await interaction.response.send_message(
                "global learning has no host guild configured (set `GLOBAL_DATA_GUILD`).", ephemeral=True)
            return
        layers = gl.layers()
        history = gl.manifests()
        last = history[-1] if history else None
        body = (f"quarantine (awaiting evidence): **{gl.quarantine_size()}**\n"
                f"global patterns → canonical: {layers['canonical']}, "
                f"experimental: {layers['experimental']}, retired: {layers['retired']}\n")
        if last:
            body += (f"\nlast cycle {last.get('period')}: promoted {last.get('promoted')}, "
                     f"refined {last.get('refined')}, rejected {last.get('rejected')}, "
                     f"held for more evidence {last.get('insufficient_independence')}")
        else:
            body += "\nno monthly cycle has run yet."
        await interaction.response.send_message(body, ephemeral=True)

    @globallearn.command(name="run", description="Run the monthly global-learning cycle now (server managers only).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def globallearn_run(self, interaction: discord.Interaction) -> None:
        intel = self._intel()
        if intel is None or not config.GLOBAL_LEARNING_ENABLED:
            await interaction.response.send_message("global learning is off.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        manifest = await intel.run_global_cycle(self.bot)
        if manifest.get("error"):
            await interaction.followup.send(manifest["error"], ephemeral=True)
            return
        await interaction.followup.send(
            f"cycle **{manifest.get('period')}** done — evaluated {manifest.get('evaluated')}, "
            f"harvested {manifest.get('harvested')}, promoted {manifest.get('promoted')} "
            f"(canonical {manifest.get('canonical')}, experimental {manifest.get('experimental')}), "
            f"refined {manifest.get('refined')}, rejected {manifest.get('rejected')}, "
            f"retired {manifest.get('retired')}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(IntelligenceCog(bot))
