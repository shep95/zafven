"""LearningGate — the hard boundary between "the model proposed learning" and
"the system persisted learning" (§25).

The model can only PROPOSE: a memory to remember, a correction to learn, an outcome.
The gate decides whether anything is written, and at what scope. Two rules it
enforces here beyond what memory/creator already do:

  • one piece of feedback never mints a GLOBAL truth (§12). Feedback that the model
    tries to scope 'global' is downgraded to a DOMAIN candidate — global promotion
    is only ever the monthly, evidence-aggregated, privacy-abstracted path (globals).

  • memory proposals still pass through the ON/OFF + candidate gate in MemoryVault;
    the gate never bypasses it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.intelligence.creator import AdaptivePatternCreator
from core.intelligence.memory import MemoryVault
from core.intelligence.pattern import Pattern
from core.intelligence.scope import Scope

log = logging.getLogger("zafven.intel.learning")


@dataclass
class LearningResult:
    memory_outcome: str = "skipped"   # stored | candidate | refused | skipped
    pattern: Pattern | None = None
    note: str = ""


class LearningGate:
    def __init__(self, memory: MemoryVault, creator: AdaptivePatternCreator) -> None:
        self._memory = memory
        self._creator = creator

    async def propose_memory(
        self, text: str, *, user_id: int = 0, hinted_scope: Scope | None = None,
        source: str = "conversation",
    ) -> str:
        """Route a model-proposed memory through the vault's promotion gate."""
        outcome, _item = await self._memory.offer(
            text, user_id=user_id, hinted_scope=hinted_scope, source=source)
        return outcome

    async def propose_feedback_pattern(
        self, feedback: str, *, context: str = "", domain: str = "general",
        hinted_scope: Scope | None = None,
    ) -> Pattern | None:
        """Route user feedback to the pattern creator as a scoped CANDIDATE, enforcing
        the 'no instant global truth' rule."""
        pattern = await self._creator.from_feedback(
            feedback, context=context, domain=domain, hinted_scope=hinted_scope)
        if pattern and pattern.scope is Scope.GLOBAL:
            # downgrade: one correction is not population-level evidence (§12/§26).
            pattern.scope = Scope.DOMAIN
            pattern.evidence.append("scope downgraded from global: single-instance feedback")
            await self._creator._reg.update(pattern)  # keep the correction, not the overreach
            log.info("downgraded feedback pattern %s from global→domain", pattern.id)
        return pattern

    async def record_outcome(self, pattern_id: str, success: bool, context: str = "") -> Pattern | None:
        """A real result folds back into a pattern's evidence + lifecycle."""
        return await self._creator._reg.record_outcome(pattern_id, success, context)
