"""Global learning — population-level pattern evolution WITHOUT exporting private data.

The absolute rule (§27): raw user or project information never becomes global
knowledge. Only privacy-abstracted MECHANISMS cross the boundary, through a
quarantine + monthly evaluation pipeline (§26/§28):

    local candidate → privacy abstraction → scrub check → quarantine
      → monthly: dedup → independence analysis → evidence aggregation
      → generalization → evaluation → promote / refine / experimental / reject / retire

Honest single-instance scope: this bot instance only sees the guilds IT serves, so
"population" here means "across this instance's guilds", not a true multi-deployment
population. Independence analysis therefore counts DISTINCT SOURCE GUILDS — repeated
copies from one guild are not independent evidence (§28).

Global data persists in one designated store (config.GLOBAL_DATA_GUILD, else the
home guild). If neither is available, global learning stays disabled and says so.
"""
from __future__ import annotations

import logging
import re
import time

from core.intelligence.pattern import Pattern, PatternStatus, Source
from core.intelligence.registry import PatternRegistry
from core.intelligence.scope import Scope

log = logging.getLogger("zafven.intel.globals")

_NS_QUARANTINE = "global_quarantine"   # [ {abstract, mechanism, sources:[guild_id], evidence, ts} ]
_NS_MANIFESTS = "global_manifests"     # [ manifest, ... ]
_NS_GLOBAL_PATTERNS = "global_patterns"

# thresholds (§28/§29) — deliberately conservative so low-evidence stays experimental
_MIN_INDEPENDENT_SOURCES = 2   # distinct guilds before a candidate can be promoted
_CANONICAL_SOURCES = 3         # distinct guilds + strong evidence → canonical
_MIN_EVIDENCE = 4              # total observations aggregated

# privacy scrub — leftover raw identifiers that must NOT reach global storage
_ID_RE = re.compile(r"<[@#!&][0-9]+>|\b\d{15,}\b")           # discord mentions / snowflakes
_PERSONAL_RE = re.compile(r"\b(user|member|@\w+|my |his |her |their name)\b", re.I)


def _scrub(text: str) -> str:
    """Remove obvious raw identifiers. Abstraction (LLM) does the real generalization;
    this is the mechanical safety net."""
    return _ID_RE.sub("", text or "").strip()


def _looks_personal(text: str) -> bool:
    """True if the abstracted text still carries person/guild-specific residue → it is
    rejected at the boundary rather than promoted (§27)."""
    if _ID_RE.search(text or ""):
        return True
    return bool(_PERSONAL_RE.search(text or ""))


def layer_of(p: Pattern) -> str:
    """Map lifecycle status to the global layer (§30)."""
    if p.status in {PatternStatus.ACTIVE, PatternStatus.REFINED}:
        return "canonical"
    if p.status is PatternStatus.ARCHIVED:
        return "retired"
    return "experimental"


class GlobalLearning:
    def __init__(self, global_store: object, provider=None) -> None:
        self._store = global_store
        self._provider = provider
        self.registry = PatternRegistry(global_store, _NS_GLOBAL_PATTERNS)

    # ---- abstraction gateway (§27) ----------------------------------------
    async def _abstract(self, pattern: Pattern) -> str | None:
        """Turn a local pattern's mechanism into a privacy-safe, general principle.
        Returns None if it cannot be safely abstracted."""
        base = _scrub(f"{pattern.name}: {pattern.mechanism}")
        if self._provider is not None:
            try:
                system = (
                    "you convert a specific problem-solving pattern into a GENERAL, reusable "
                    "principle. remove every reference to any person, user, server, project, or "
                    "specific data. output one or two sentences describing only the transferable "
                    "mechanism. no names, no ids, no 'the user', no specifics."
                )
                out = await self._provider.generate(
                    system, base, web_search=False, max_tokens=160, temperature=0.2, uncensored=False)
                out = _scrub(out)
                if out and not _looks_personal(out):
                    return out[:400]
            except Exception as exc:  # noqa: BLE001
                log.info("abstraction call failed: %s", exc)
        # fallback: only accept the scrubbed original if it isn't personal
        return base[:400] if base and not _looks_personal(base) else None

    # ---- quarantine (§26) --------------------------------------------------
    async def submit_candidate(self, pattern: Pattern, source_guild_id: int) -> str:
        """Abstract a local candidate and place it in quarantine, merging with a
        similar existing one to aggregate independent evidence. Returns an outcome:
        'quarantined' | 'merged' | 'rejected'."""
        if pattern.scope is Scope.GLOBAL:
            return "rejected"  # already global; nothing to promote
        abstract = await self._abstract(pattern)
        if not abstract:
            log.info("global: candidate %s rejected at privacy boundary", pattern.id)
            return "rejected"
        pool = list(self._store.get(_NS_QUARANTINE, []) or [])  # type: ignore[attr-defined]
        atoks = _tok(abstract)
        for entry in pool:
            if len(atoks & _tok(entry.get("mechanism", ""))) >= max(3, len(atoks) // 2):
                srcs = set(entry.get("sources", []))
                srcs.add(source_guild_id)
                entry["sources"] = list(srcs)
                entry["evidence"] = int(entry.get("evidence", 0)) + max(1, pattern.success_count)
                entry["ts"] = int(time.time())
                await self._store.set(_NS_QUARANTINE, pool)  # type: ignore[attr-defined]
                return "merged"
        pool.append({
            "abstract": abstract,
            "mechanism": abstract,
            "name": _scrub(pattern.name)[:80] or "global candidate",
            "domain": pattern.domain,
            "sources": [source_guild_id],
            "evidence": max(1, pattern.success_count),
            "ts": int(time.time()),
        })
        await self._store.set(_NS_QUARANTINE, pool[-500:])  # type: ignore[attr-defined]
        return "quarantined"

    # ---- monthly evaluation (§28/§29) -------------------------------------
    async def run_monthly_cycle(self) -> dict:
        """Evaluate quarantined candidates and promote/refine/reject/retire. Produces
        an auditable manifest (§33) with real counts (never fabricated)."""
        period = time.strftime("%Y-%m")
        pool = list(self._store.get(_NS_QUARANTINE, []) or [])  # type: ignore[attr-defined]
        manifest = {
            "period": period, "evaluated": len(pool), "promoted": 0, "canonical": 0,
            "experimental": 0, "rejected": 0, "refined": 0, "retired": 0,
            "insufficient_independence": 0, "generated_at": int(time.time()),
        }
        survivors: list[dict] = []
        for entry in pool:
            sources = set(entry.get("sources", []))
            evidence = int(entry.get("evidence", 0))
            # independence analysis: distinct guilds, not repeated copies (§28)
            if len(sources) < _MIN_INDEPENDENT_SOURCES or evidence < _MIN_EVIDENCE:
                manifest["insufficient_independence"] += 1
                # keep in quarantine to keep aggregating, unless stale
                if int(time.time()) - int(entry.get("ts", 0)) < 90 * 86400:
                    survivors.append(entry)
                else:
                    manifest["rejected"] += 1
                continue
            mechanism = entry.get("mechanism", "")
            if _looks_personal(mechanism):   # last-line privacy guard before promotion
                manifest["rejected"] += 1
                continue
            strong = len(sources) >= _CANONICAL_SOURCES and evidence >= _MIN_EVIDENCE * 2
            status = PatternStatus.ACTIVE if strong else PatternStatus.VALIDATED
            existing = self._find_similar_global(mechanism)
            if existing is not None:
                # refine: new evidence into a NEW VERSION, never overwrite (§31)
                await self.registry.new_version(
                    existing.id, mechanism=mechanism, evidence_quality="strong" if strong else "moderate")
                manifest["refined"] += 1
            else:
                p = Pattern(
                    name=entry.get("name", "global pattern")[:80],
                    mechanism=mechanism[:600],
                    domain=entry.get("domain", "general"),
                    scope=Scope.GLOBAL,
                    status=status,
                    source=Source.GLOBAL_PROMOTION,
                    confidence=0.75 if strong else 0.55,
                    evidence_quality="strong" if strong else "moderate",
                    evidence=[f"aggregated across {len(sources)} guilds, {evidence} observations"],
                    success_count=evidence,
                )
                await self.registry.add(p)
                manifest["promoted"] += 1
                manifest["canonical" if strong else "experimental"] += 1
            # promoted candidates leave quarantine
        await self._store.set(_NS_QUARANTINE, survivors)  # type: ignore[attr-defined]
        # retire stale experimental globals with no supporting evidence over time
        manifest["retired"] += await self._retire_stale()
        await self._save_manifest(manifest)
        log.info("global monthly cycle %s: %s", period, manifest)
        return manifest

    def _find_similar_global(self, mechanism: str) -> Pattern | None:
        toks = _tok(mechanism)
        best = None
        best_overlap = 0
        for p in self.registry.all():
            if p.status in {PatternStatus.SUPERSEDED, PatternStatus.ARCHIVED}:
                continue
            ov = len(toks & _tok(p.mechanism))
            if ov > best_overlap and ov >= max(3, len(toks) // 2):
                best, best_overlap = p, ov
        return best

    async def _retire_stale(self) -> int:
        retired = 0
        cutoff = int(time.time()) - 180 * 86400
        for p in self.registry.all():
            if (p.status is PatternStatus.VALIDATED and p.updated_at < cutoff
                    and p.success_count < _MIN_EVIDENCE):
                await self.registry.retire(p.id, "stale experimental global, insufficient evidence")
                retired += 1
        return retired

    async def _save_manifest(self, manifest: dict) -> None:
        history = list(self._store.get(_NS_MANIFESTS, []) or [])  # type: ignore[attr-defined]
        history.append(manifest)
        await self._store.set(_NS_MANIFESTS, history[-36:])  # type: ignore[attr-defined]

    def manifests(self) -> list[dict]:
        return list(self._store.get(_NS_MANIFESTS, []) or [])  # type: ignore[attr-defined]

    def layers(self) -> dict[str, int]:
        out = {"canonical": 0, "experimental": 0, "retired": 0}
        for p in self.registry.all():
            out[layer_of(p)] = out.get(layer_of(p), 0) + 1
        return out

    def quarantine_size(self) -> int:
        return len(self._store.get(_NS_QUARANTINE, []) or [])  # type: ignore[attr-defined]

    def retrieve(self, query: str, limit: int = 2) -> list[Pattern]:
        """Global patterns relevant to a query — surfaced to the runtime but never as
        an override of local context (§32); the resolver marks scope so local wins."""
        return self.registry.retrieve(query, scopes={Scope.GLOBAL}, limit=limit)


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "are", "with", "that", "this", "when", "from", "into", "than"}


def _tok(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}
