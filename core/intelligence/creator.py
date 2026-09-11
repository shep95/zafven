"""AdaptivePatternCreator — the layer that turns experience into reusable patterns.

This is the part that makes the system adapt its PROBLEM-SOLVING STRATEGY, not just
its output (§11/§12/§44). It:

  • detects UNKNOWN — when no sufficiently-applicable pattern covers a problem, it
    says so instead of forcing a known one or hallucinating one (§13);
  • discovers a candidate pattern for an unknown problem (§14), as a HYPOTHESIS;
  • turns user FEEDBACK into a scoped candidate pattern (§12) — e.g. "stop adding
    abstraction layers for simple fixes" becomes a candidate reasoning pattern;
  • composes new candidates from existing patterns (§16);
  • records failures with the condition they failed under (§18).

Everything it produces enters the registry as a CANDIDATE (a hypothesis), never as
established truth. Only accumulated outcomes (registry.record_outcome) promote it.
That is the learning gate boundary (§25): the model proposes; the system decides.

LLM calls go through the ProviderGateway but are always wrapped — if the model is
unavailable the creator falls back to a heuristic candidate so chat never breaks.
"""
from __future__ import annotations

import enum
import json
import logging
import re

from core.intelligence.pattern import Pattern, PatternStatus, Relation, Source
from core.intelligence.registry import PatternRegistry
from core.intelligence.scope import Scope, parse as parse_scope

log = logging.getLogger("zafven.intel.creator")


class Coverage(enum.Enum):
    """Problem coverage state (§13). Unknown is a first-class state, not an error."""
    KNOWN = "known"          # a validated/active pattern applies well
    UNCERTAIN = "uncertain"  # only weak or candidate patterns apply
    UNKNOWN = "unknown"      # nothing applicable → trigger discovery

    def __str__(self) -> str:
        return self.value


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM reply, tolerating code fences/prose."""
    if not text:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def assess_coverage(registry: PatternRegistry, query: str, domain: str = "") -> tuple[Coverage, list[Pattern]]:
    """Decide whether the pattern library already covers this problem."""
    applicable = registry.retrieve(query, domain=domain or None, limit=4, include_candidates=False)
    if applicable and max(p.confidence for p in applicable) >= 0.6:
        return Coverage.KNOWN, applicable
    considered = registry.retrieve(query, domain=domain or None, limit=4, include_candidates=True)
    if considered:
        return Coverage.UNCERTAIN, considered
    return Coverage.UNKNOWN, []


class AdaptivePatternCreator:
    def __init__(self, registry: PatternRegistry, provider) -> None:
        self._reg = registry
        self._provider = provider  # a GeminiProvider (or None to force heuristics)

    # ---- feedback → candidate pattern (§12) -------------------------------
    async def from_feedback(
        self, feedback: str, *, context: str = "", domain: str = "general",
        hinted_scope: Scope | None = None,
    ) -> Pattern | None:
        """Treat user feedback as evidence about the process that produced the
        disliked result, and mint a scoped CANDIDATE pattern that changes future
        behavior. Returns the created candidate, or None if nothing actionable."""
        data = await self._ask_for_pattern(
            instruction=(
                "A user gave feedback about how you worked (not just this one answer). "
                "Identify the underlying behavior/reasoning pattern that caused what they "
                "disliked, and describe the CORRECTED reusable pattern to apply next time. "
                "Classify its scope: 'task' (this request only), 'conversation', 'project' "
                "(this whole server), 'user' (this person's preference), 'domain' (this kind "
                "of problem), or 'global' (a general principle). Be conservative: prefer "
                "'user' or 'domain' unless it is clearly a universal principle."
            ),
            payload=f"USER FEEDBACK:\n{feedback}\n\nCONTEXT:\n{context}",
        )
        if not data:
            # heuristic fallback: keep the raw correction as a user-scoped candidate
            if len((feedback or "").strip()) < 8:
                return None
            return await self._create(
                name=f"correction: {feedback.strip()[:48]}",
                mechanism=feedback.strip()[:400],
                trigger="a similar request in this context",
                scope=hinted_scope or Scope.USER,
                domain=domain,
                source=Source.USER_FEEDBACK,
                evidence=[f"user feedback: {feedback.strip()[:200]}"],
            )
        scope = parse_scope(data.get("scope"), hinted_scope or Scope.USER)
        return await self._create(
            name=(data.get("name") or "learned correction")[:80],
            mechanism=(data.get("mechanism") or data.get("corrected_pattern") or "")[:600],
            trigger=(data.get("trigger") or "")[:200],
            scope=scope,
            domain=(data.get("domain") or domain)[:40],
            source=Source.USER_FEEDBACK,
            procedure=[str(s)[:120] for s in (data.get("procedure") or [])][:8],
            fails_under=(data.get("avoid") or "")[:200],
            evidence=[f"user feedback: {feedback.strip()[:200]}"],
        )

    # ---- discovery for an unknown problem (§14) ---------------------------
    async def discover(self, problem: str, *, context: str = "", domain: str = "general") -> Pattern | None:
        """When coverage is UNKNOWN, synthesize a candidate strategy — a HYPOTHESIS —
        by decomposing the problem and looking for a cross-domain mechanism (§15)."""
        data = await self._ask_for_pattern(
            instruction=(
                "No known pattern covers this problem. Decompose it into its underlying "
                "structure (mechanisms, states, constraints, goal), then propose ONE reusable "
                "problem-solving pattern as a HYPOTHESIS — ideally by transferring a mechanism "
                "from another domain where this same structure appears. Keep it falsifiable."
            ),
            payload=f"PROBLEM:\n{problem}\n\nCONTEXT:\n{context}",
        )
        if not data:
            return None
        return await self._create(
            name=(data.get("name") or "discovered strategy")[:80],
            mechanism=(data.get("mechanism") or "")[:600],
            trigger=(data.get("trigger") or problem[:120])[:200],
            scope=parse_scope(data.get("scope"), Scope.DOMAIN),
            domain=(data.get("domain") or domain)[:40],
            source=Source.EXPERIMENT,
            procedure=[str(s)[:120] for s in (data.get("procedure") or [])][:8],
            evidence=[f"discovered for: {problem[:160]}"],
        )

    # ---- composition (§16) -------------------------------------------------
    async def compose(self, a_id: str, b_id: str, new_constraint: str = "") -> Pattern | None:
        a = self._reg.get(a_id)
        b = self._reg.get(b_id)
        if not a or not b:
            return None
        mech = f"combine [{a.name}]: {a.mechanism}  +  [{b.name}]: {b.mechanism}"
        if new_constraint:
            mech += f"  under constraint: {new_constraint}"
        composite = await self._create(
            name=f"{a.name} + {b.name}"[:80],
            mechanism=mech[:600],
            trigger=(a.trigger or b.trigger)[:200],
            scope=a.scope if a.scope == b.scope else Scope.DOMAIN,
            domain=a.domain,
            source=Source.PATTERN_COMPOSITION,
            constraints=([new_constraint] if new_constraint else []),
        )
        if composite:
            await self._reg.relate(composite.id, Relation.DERIVED_FROM, a.id)
            await self._reg.relate(composite.id, Relation.DERIVED_FROM, b.id)
        return composite

    # ---- failure recording (§18) ------------------------------------------
    async def record_failure(self, pattern_id: str, condition: str) -> Pattern | None:
        p = self._reg.get(pattern_id)
        if not p:
            return None
        if condition and condition not in p.failure_modes:
            p.failure_modes.append(condition[:200])
        p.fails_under = (p.fails_under + f" | {condition}").strip(" |")[:300] if p.fails_under else condition[:300]
        await self._reg.record_outcome(pattern_id, success=False, context=condition[:60])
        return self._reg.get(pattern_id)

    # ---- internals ---------------------------------------------------------
    async def _create(self, **kwargs) -> Pattern:
        """Build a CANDIDATE pattern (hypothesis) and register it."""
        p = Pattern(
            name=kwargs.pop("name"),
            mechanism=kwargs.pop("mechanism"),
            status=PatternStatus.CANDIDATE,
            confidence=0.25,
            evidence_quality="weak",
            **kwargs,
        )
        await self._reg.add(p)
        log.info("created candidate pattern %s (%s, scope=%s)", p.id, p.name, p.scope)
        return p

    async def _ask_for_pattern(self, *, instruction: str, payload: str) -> dict | None:
        """Ask the model for a structured pattern as strict JSON. Returns the parsed
        object, or None on any failure (caller falls back to a heuristic)."""
        if self._provider is None:
            return None
        system = (
            "you extract reusable problem-solving patterns. respond with ONE json object "
            "and nothing else, using these keys: name (short), trigger (when it applies), "
            "mechanism (what to do — the core), procedure (array of steps, optional), scope "
            "(one of task/conversation/project/user/domain/global), domain (short), avoid "
            "(what NOT to do, optional). no prose, no code fences."
        )
        try:
            raw = await self._provider.generate(
                system, f"{instruction}\n\n{payload}",
                web_search=False, max_tokens=400, temperature=0.3, uncensored=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.info("pattern extraction call failed: %s", exc)
            return None
        return _extract_json(raw)
