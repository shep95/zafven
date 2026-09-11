"""PatternRegistry — a store-backed GRAPH of patterns (not a flat list, §19).

One registry wraps one store namespace, so the same class serves a per-guild
(PROJECT) registry and the cross-guild GLOBAL registry. It persists to zafven's
Discord-backed JSON store, keeps an in-memory view, and enforces the rules the
spec is strict about:

  • versioning never overwrites — a new version SUPERSEDES the old, which is kept
    with its evidence and failure history intact (§31);
  • retrieval is relevance-based, not "inject everything" (§46);
  • only VALIDATED/ACTIVE/REFINED patterns are applied; CANDIDATE/TESTING ones can
    be surfaced for consideration but are flagged as hypotheses (§13/§18).
"""
from __future__ import annotations

import re
import time

from core.intelligence.pattern import Pattern, PatternStatus, Relation
from core.intelligence.scope import Scope

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "are", "was", "you", "your", "that", "this", "with",
    "from", "what", "when", "where", "which", "who", "why", "how", "does", "did",
    "can", "could", "would", "should", "about", "into", "than", "then", "they",
    "them", "have", "has", "had", "but", "not", "all", "any", "out", "get",
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


class PatternRegistry:
    """Patterns + edges for one namespace. `store` is a DiscordStore-like object
    exposing sync `get(ns, default)` and async `set(ns, data)`."""

    def __init__(self, store: object, namespace: str = "patterns") -> None:
        self._store = store
        self._ns = namespace
        self._patterns: dict[str, Pattern] = {}
        self._edges: list[dict] = []
        self._loaded = False

    # ---- persistence -------------------------------------------------------
    def load(self) -> None:
        if self._loaded:
            return
        raw = self._store.get(self._ns, {}) or {}  # type: ignore[attr-defined]
        for pid, pd in (raw.get("patterns", {}) or {}).items():
            try:
                self._patterns[pid] = Pattern.from_dict(pd)
            except Exception:  # noqa: BLE001 — a corrupt row must not sink the registry
                continue
        self._edges = list(raw.get("edges", []) or [])
        self._loaded = True

    async def _save(self) -> None:
        data = {
            "patterns": {pid: p.to_dict() for pid, p in self._patterns.items()},
            "edges": self._edges,
        }
        await self._store.set(self._ns, data)  # type: ignore[attr-defined]

    # ---- CRUD --------------------------------------------------------------
    async def add(self, pattern: Pattern) -> str:
        self.load()
        self._patterns[pattern.id] = pattern
        await self._save()
        return pattern.id

    def get(self, pattern_id: str) -> Pattern | None:
        self.load()
        return self._patterns.get(pattern_id)

    def all(self) -> list[Pattern]:
        self.load()
        return list(self._patterns.values())

    async def update(self, pattern: Pattern) -> None:
        self.load()
        pattern.touch()
        self._patterns[pattern.id] = pattern
        await self._save()

    async def set_status(self, pattern_id: str, status: PatternStatus) -> bool:
        p = self.get(pattern_id)
        if not p:
            return False
        p.status = status
        await self.update(p)
        return True

    async def record_outcome(self, pattern_id: str, success: bool, context: str = "") -> Pattern | None:
        """Fold a real outcome into a pattern and auto-advance its lifecycle:
        enough successful evidence promotes CANDIDATE/TESTING → VALIDATED → ACTIVE;
        a validated pattern that keeps failing falls to FAILED (keeping why)."""
        p = self.get(pattern_id)
        if not p:
            return None
        p.record_outcome(success, context)
        total = p.success_count + p.failure_count
        rate = p.confidence
        if p.status in {PatternStatus.CANDIDATE, PatternStatus.TESTING}:
            if total >= 3 and rate >= 0.66:
                p.status = PatternStatus.VALIDATED
            elif total >= 3 and rate < 0.34:
                p.status = PatternStatus.FAILED
                p.fails_under = p.fails_under or "repeatedly failed in early trials"
        elif p.status in {PatternStatus.VALIDATED, PatternStatus.ACTIVE, PatternStatus.REFINED}:
            if p.status is PatternStatus.VALIDATED and total >= 5 and rate >= 0.7:
                p.status = PatternStatus.ACTIVE
            elif total >= 5 and rate < 0.3:
                p.status = PatternStatus.FAILED
        await self.update(p)
        return p

    # ---- versioning (never overwrite, §31) --------------------------------
    async def new_version(self, old_id: str, **changes) -> Pattern | None:
        """Create v(n+1) of a pattern from `changes`, mark the old one SUPERSEDED,
        and link them. The old version is preserved with its evidence/failures."""
        old = self.get(old_id)
        if not old:
            return None
        data = old.to_dict()
        data.pop("id", None)
        data.update(changes)
        new = Pattern.from_dict(data)
        new.version = old.version + 1
        new.supersedes_version_of = old.id
        new.status = PatternStatus.ACTIVE if old.status in {
            PatternStatus.ACTIVE, PatternStatus.REFINED, PatternStatus.VALIDATED
        } else new.status
        # fresh evidence for the new version; the old keeps its own record
        new.success_count = 0
        new.failure_count = 0
        new.created_at = int(time.time())
        old.status = PatternStatus.SUPERSEDED
        await self.update(old)
        await self.add(new)
        await self.relate(new.id, Relation.SUPERSEDES, old.id)
        return new

    async def retire(self, pattern_id: str, reason: str = "") -> bool:
        p = self.get(pattern_id)
        if not p:
            return False
        p.status = PatternStatus.ARCHIVED
        if reason:
            p.fails_under = (p.fails_under + f" | retired: {reason}").strip(" |")
        await self.update(p)
        return True

    # ---- graph -------------------------------------------------------------
    async def relate(self, src: str, rel: Relation, dst: str, meta: dict | None = None) -> None:
        self.load()
        edge = {"src": src, "rel": str(rel), "dst": dst, "meta": meta or {}}
        if edge not in self._edges:
            self._edges.append(edge)
            await self._save()

    def relations(self, pattern_id: str, rel: Relation | None = None) -> list[dict]:
        self.load()
        want = str(rel) if rel else None
        return [e for e in self._edges
                if (e.get("src") == pattern_id or e.get("dst") == pattern_id)
                and (want is None or e.get("rel") == want)]

    def neighbors(self, pattern_id: str, rel: Relation) -> list[Pattern]:
        out: list[Pattern] = []
        for e in self.relations(pattern_id, rel):
            other = e["dst"] if e["src"] == pattern_id else e["src"]
            p = self.get(other)
            if p:
                out.append(p)
        return out

    # ---- relevance retrieval (§46) ----------------------------------------
    def retrieve(
        self,
        query: str,
        *,
        scopes: set[Scope] | None = None,
        domain: str | None = None,
        limit: int = 4,
        include_candidates: bool = False,
    ) -> list[Pattern]:
        """Rank patterns by keyword overlap with the query, weighted by confidence.
        Only applicable (VALIDATED/ACTIVE/REFINED) patterns unless include_candidates."""
        self.load()
        q = _tokens(query)
        if domain:
            q |= _tokens(domain)
        if not q:
            return []
        scored: list[tuple[float, Pattern]] = []
        for p in self._patterns.values():
            if not include_candidates and not p.is_applicable():
                continue
            if p.status in {PatternStatus.SUPERSEDED, PatternStatus.ARCHIVED}:
                continue
            if scopes and p.scope not in scopes:
                continue
            if domain and p.domain and p.domain != "general" and domain not in p.domain and p.domain not in domain:
                # domain filter is soft: mismatched domain just isn't a hard exclude
                pass
            toks = _tokens(f"{p.name} {p.trigger} {p.mechanism} {p.description} {p.domain} {p.subdomain}")
            overlap = len(q & toks)
            if not overlap:
                continue
            # applicable patterns weighted by confidence; candidates discounted
            weight = p.confidence if p.is_applicable() else p.confidence * 0.4
            scored.append((overlap * (0.5 + weight), p))
        scored.sort(key=lambda t: (-t[0], -t[1].updated_at))
        return [p for _s, p in scored[:limit]]

    def counts_by_status(self) -> dict[str, int]:
        self.load()
        out: dict[str, int] = {}
        for p in self._patterns.values():
            out[str(p.status)] = out.get(str(p.status), 0) + 1
        return out
