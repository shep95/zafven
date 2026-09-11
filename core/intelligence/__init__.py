"""Asherin intelligence layer — the orchestrator that wires the subsystems together.

Data flow (the spec's target architecture, §5/§49), realized on zafven:

    message → context resolver → (conversation state + user memory + project memory
    + relevant patterns + relevant global patterns) → persona/model prompt → provider
    gateway → reply → validator → outcome → learning gate → candidate memory / candidate
    pattern → (monthly) global learning

The model is a replaceable capability at the bottom; Asherin owns the intelligence
around it. Everything is scoped and isolated per guild/user. Persistence reuses
zafven's Discord-backed JSON store, so no new infrastructure is required.

Everything here is fail-open: if any subsystem errors, chat still works — the layer
degrades to "no extra intelligence" rather than breaking the bot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import config
from core import store as store_mod
from core.model_gateway import ModelGateway
from core.intelligence.context import ConversationStore, ResolvedContext
from core.intelligence.creator import AdaptivePatternCreator, assess_coverage, Coverage
from core.intelligence.critic import validate_reply
from core.intelligence.gateway import ProviderGateway, CredentialVault, GeminiProvider
from core.intelligence.globals import GlobalLearning
from core.intelligence.learning import LearningGate
from core.intelligence.memory import MemoryVault
from core.intelligence.pattern import Pattern, PatternStatus
from core.intelligence.registry import PatternRegistry
from core.intelligence.scope import Scope

log = logging.getLogger("zafven.intel")

__all__ = [
    "Intelligence", "GuildIntelligence", "ResolvedContext", "Scope", "Pattern",
    "Coverage", "assess_coverage", "validate_reply",
]


@dataclass
class GuildIntelligence:
    """The per-guild bundle of intelligence subsystems, all sharing that guild's
    store (so PROJECT-scoped data is naturally isolated per guild)."""
    guild_id: int
    registry: PatternRegistry
    memory: MemoryVault
    credentials: CredentialVault
    provider: GeminiProvider
    creator: AdaptivePatternCreator
    learning: LearningGate


class Intelligence:
    def __init__(self, model_gateway: ModelGateway) -> None:
        self._gateway = ProviderGateway(model_gateway)
        self.conversations = ConversationStore()
        self._guilds: dict[int, GuildIntelligence] = {}
        self._global: GlobalLearning | None = None

    # ---- per-guild bundle --------------------------------------------------
    async def for_guild(self, guild) -> GuildIntelligence:
        gid = guild.id
        cached = self._guilds.get(gid)
        if cached is not None:
            return cached
        gstore = await store_mod.get_store(guild)
        registry = PatternRegistry(gstore, "patterns")
        registry.load()
        memory = MemoryVault(gstore)
        creds = CredentialVault(gstore)
        provider = await self._gateway.provider_for(gid, creds)
        creator = AdaptivePatternCreator(registry, provider)
        learning = LearningGate(memory, creator)
        bundle = GuildIntelligence(gid, registry, memory, creds, provider, creator, learning)
        self._guilds[gid] = bundle
        return bundle

    def invalidate_guild(self, guild_id: int) -> None:
        self._guilds.pop(guild_id, None)
        self._gateway.invalidate(guild_id)

    # ---- context resolution (§46 — relevant, not everything) --------------
    async def resolve(
        self, guild, *, channel_id: int, user_id: int, query: str, domain: str = "general",
    ) -> ResolvedContext:
        """Assemble the runtime context: conversation state + relevant user/project
        memory + relevant patterns (+ global). Fail-open to an empty context."""
        rc = ResolvedContext()
        try:
            gi = await self.for_guild(guild)
        except Exception:  # noqa: BLE001
            log.exception("intelligence.resolve: bundle build failed")
            return rc
        try:
            ctx = self.conversations.get(channel_id, guild.id)
            rc.conversation_block = ctx.as_prompt_block()
        except Exception:  # noqa: BLE001
            pass
        try:
            rc.user_memory = gi.memory.retrieve_user(user_id, query)
            rc.project_memory = gi.memory.retrieve_project(query)
        except Exception:  # noqa: BLE001
            pass
        try:
            pats = gi.registry.retrieve(
                query, domain=domain, limit=4,
                scopes={Scope.PROJECT, Scope.DOMAIN, Scope.USER, Scope.CONVERSATION},
                include_candidates=False)
            rc.patterns = pats
            for p in pats:
                self.conversations.get(channel_id, guild.id).used_pattern(p.id)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._global is not None:
                rc.global_patterns = self._global.retrieve(query, limit=2)
        except Exception:  # noqa: BLE001
            pass
        return rc

    # ---- learning proposals (routed through the gate) ---------------------
    async def learn_memory(self, guild, text: str, *, user_id: int,
                           hinted_scope: Scope | None = None) -> str:
        try:
            gi = await self.for_guild(guild)
            return await gi.learning.propose_memory(text, user_id=user_id, hinted_scope=hinted_scope)
        except Exception:  # noqa: BLE001
            log.exception("learn_memory failed")
            return "skipped"

    async def learn_feedback(self, guild, feedback: str, *, context: str = "",
                             domain: str = "general") -> Pattern | None:
        try:
            gi = await self.for_guild(guild)
            return await gi.learning.propose_feedback_pattern(feedback, context=context, domain=domain)
        except Exception:  # noqa: BLE001
            log.exception("learn_feedback failed")
            return None

    async def record_pattern_outcome(self, guild, pattern_id: str, success: bool,
                                     context: str = "") -> None:
        try:
            gi = await self.for_guild(guild)
            await gi.learning.record_outcome(pattern_id, success, context)
        except Exception:  # noqa: BLE001
            pass

    # ---- global learning ---------------------------------------------------
    async def ensure_global(self, bot) -> GlobalLearning | None:
        """Bind the global-learning store once. Uses GLOBAL_DATA_GUILD, else the home
        guild (GUILD_ID), else the first guild the bot is in. Disabled if none."""
        if self._global is not None:
            return self._global
        target_id = getattr(config, "GLOBAL_DATA_GUILD", 0) or config.GUILD_ID or 0
        guild = None
        if target_id:
            guild = bot.get_guild(int(target_id))
        if guild is None and bot.guilds:
            guild = bot.guilds[0]
        if guild is None:
            log.info("global learning: no guild available to host global store; disabled")
            return None
        gstore = await store_mod.get_store(guild)
        self._global = GlobalLearning(gstore, provider=self._gateway.builtin())
        self._global.registry.load()
        log.info("global learning bound to guild %s store", guild.id)
        return self._global

    async def run_global_cycle(self, bot) -> dict:
        """Harvest promotable local patterns from every guild into the global
        quarantine (abstracted), then run the monthly evaluation. Returns the manifest."""
        gl = await self.ensure_global(bot)
        if gl is None:
            return {"error": "global learning disabled (no host guild configured)"}
        harvested = 0
        for guild in list(bot.guilds):
            try:
                gi = await self.for_guild(guild)
                for p in gi.registry.all():
                    if p.scope in {Scope.PROJECT, Scope.DOMAIN} and p.status in {
                        PatternStatus.VALIDATED, PatternStatus.ACTIVE, PatternStatus.REFINED
                    }:
                        outcome = await gl.submit_candidate(p, guild.id)
                        if outcome in {"quarantined", "merged"}:
                            harvested += 1
            except Exception:  # noqa: BLE001
                log.exception("global harvest failed for guild %s", getattr(guild, "id", "?"))
        manifest = await gl.run_monthly_cycle()
        manifest["harvested"] = harvested
        return manifest
