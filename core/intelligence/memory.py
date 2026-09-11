"""Memory vaults + the promotion gate + the hard ON/OFF boundary.

Three things the spec insists on and this module enforces:

  1. Memory ≠ conversation state (§7/§44). Conversation state lives in context.py
     and is ephemeral. This module is the DURABLE store, and it is scoped.

  2. Nothing is dumped into durable memory just because the model observed it
     (§7). Observations become CANDIDATES; a candidate is only promoted into a
     vault after classification + a policy check + (for user memory) the ON switch.

  3. A true ON/OFF boundary (§8). When user memory is OFF, persistent USER memory
     is NEVER written — candidates for the user scope are refused at the gate. The
     current conversation still works (that's context.py, unaffected).

Scopes handled here: USER (a person, across guilds — but stored per guild here),
PROJECT (this guild/server), DOMAIN (a topic). GLOBAL is handled in globals.py.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field, asdict

import config
from core.intelligence.scope import Scope, parse as parse_scope

_NS_USER = "mem_user"          # {user_id: [item, ...]}
_NS_PROJECT = "mem_project"    # [item, ...]
_NS_CANDIDATES = "mem_candidates"  # [candidate, ...] awaiting promotion
_NS_SETTINGS = "mem_settings"  # {"user_default": bool, "users": {uid: bool}, "project": bool}

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "and", "for", "are", "you", "your", "that", "this", "with", "from",
    "what", "when", "have", "has", "they", "them", "like", "just", "about",
}

# how many independent observations a CANDIDATE needs before promotion (§47:
# one interaction is not enough evidence for durable learning)
_PROMOTE_AFTER = 2


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


@dataclass
class MemoryItem:
    text: str
    scope: Scope = Scope.USER
    kind: str = "explicit"     # identity | preference | decision | fact | workflow | explicit
    user_id: int = 0           # for USER scope
    source: str = "conversation"
    confidence: float = 0.6
    evidence_count: int = 1
    id: str = field(default_factory=lambda: "mem_" + uuid.uuid4().hex[:10])
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scope"] = str(self.scope)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryItem":
        d = dict(d)
        d["scope"] = parse_scope(d.get("scope"), Scope.USER)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ---- classification (the front of the gate) -------------------------------
_IDENTITY_RE = re.compile(r"\b(my name is|i am|i'm|call me|i go by)\b", re.I)
_PREFERENCE_RE = re.compile(r"\b(prefer|like|hate|don'?t like|rather|always|never|please (?:always|don'?t))\b", re.I)
_PROJECT_RE = re.compile(r"\b(this server|this guild|the server|our server|the community|this channel|we use|our rules)\b", re.I)


def classify(text: str, hinted_scope: Scope | None = None) -> tuple[Scope, str, bool]:
    """Classify a proposed memory into (scope, kind, persist_immediately).

    `persist_immediately` is True only for clearly durable, explicitly-stated,
    self-referential facts (someone's name, an explicit stated preference). Inferred
    or ambient observations return False → they go to the candidate pool and need
    repeated evidence before promotion (§47)."""
    t = (text or "").strip()
    scope = hinted_scope
    kind = "explicit"
    immediate = False

    if _PROJECT_RE.search(t):
        scope = scope or Scope.PROJECT
        kind = "fact"
        # an explicitly-stated fact about the server ("this server uses X", "our
        # rules are…") is durable and self-declared → promote it immediately.
        immediate = True
    if _IDENTITY_RE.search(t):
        scope = scope or Scope.USER
        kind = "identity"
        immediate = True
    elif _PREFERENCE_RE.search(t):
        scope = scope or Scope.USER
        kind = "preference"
        # an explicitly stated preference ("I prefer X") is durable; promote it
        immediate = True
    if scope is None:
        scope = Scope.USER
    return scope, kind, immediate


class MemoryVault:
    """Durable, scoped memory for one guild, backed by the guild's JSON store."""

    def __init__(self, store: object) -> None:
        self._store = store

    # ---- ON/OFF (§8) -------------------------------------------------------
    def _settings(self) -> dict:
        return dict(self._store.get(_NS_SETTINGS, {}) or {})  # type: ignore[attr-defined]

    def is_user_memory_enabled(self, user_id: int) -> bool:
        s = self._settings()
        users = s.get("users", {}) or {}
        if str(user_id) in users:
            return bool(users[str(user_id)])
        default = s.get("user_default")
        if default is None:
            default = getattr(config, "MEMORY_USER_DEFAULT_ON", True)
        return bool(default)

    async def set_user_memory(self, user_id: int, enabled: bool) -> None:
        s = self._settings()
        users = dict(s.get("users", {}) or {})
        users[str(user_id)] = bool(enabled)
        s["users"] = users
        await self._store.set(_NS_SETTINGS, s)  # type: ignore[attr-defined]

    async def set_project_memory(self, enabled: bool) -> None:
        s = self._settings()
        s["project"] = bool(enabled)
        await self._store.set(_NS_SETTINGS, s)  # type: ignore[attr-defined]

    def is_project_memory_enabled(self) -> bool:
        s = self._settings()
        v = s.get("project")
        return bool(getattr(config, "MEMORY_PROJECT_DEFAULT_ON", True)) if v is None else bool(v)

    # ---- the gate: offer a proposed memory --------------------------------
    async def offer(
        self,
        text: str,
        *,
        user_id: int = 0,
        hinted_scope: Scope | None = None,
        source: str = "conversation",
    ) -> tuple[str, MemoryItem | None]:
        """Run a model-proposed memory through the promotion gate.

        Returns (outcome, item) where outcome is one of:
          'stored'    — passed the gate and was written to a vault
          'candidate' — held in the candidate pool pending more evidence
          'refused'   — the relevant memory switch is OFF (nothing written)
          'skipped'   — empty/duplicate

        The model never writes memory directly; it can only propose (§25)."""
        text = (text or "").strip()
        if not text:
            return "skipped", None
        scope, kind, immediate = classify(text, hinted_scope)

        if scope is Scope.USER:
            if not self.is_user_memory_enabled(user_id):
                return "refused", None
            if immediate:
                item = await self._write_user(user_id, text, kind, source)
                return ("stored", item) if item else ("skipped", None)
            return await self._hold_candidate(text, scope, kind, user_id, source)

        if scope in {Scope.PROJECT, Scope.DOMAIN}:
            if not self.is_project_memory_enabled():
                return "refused", None
            if immediate:
                item = await self._write_project(text, kind, source, scope)
                return ("stored", item) if item else ("skipped", None)
            return await self._hold_candidate(text, scope, kind, user_id, source)

        return "candidate", None

    # ---- candidate pool ----------------------------------------------------
    async def _hold_candidate(
        self, text: str, scope: Scope, kind: str, user_id: int, source: str,
    ) -> tuple[str, MemoryItem | None]:
        cands = [MemoryItem.from_dict(c) for c in (self._store.get(_NS_CANDIDATES, []) or [])]  # type: ignore[attr-defined]
        # merge with an existing similar candidate → accrue evidence
        tks = _tokens(text)
        for c in cands:
            if c.scope == scope and c.user_id == user_id and len(tks & _tokens(c.text)) >= max(2, len(tks) // 2):
                c.evidence_count += 1
                c.confidence = round(min(0.95, c.confidence + 0.1), 3)
                c.updated_at = int(time.time())
                if c.evidence_count >= _PROMOTE_AFTER:
                    cands = [x for x in cands if x.id != c.id]
                    await self._store.set(_NS_CANDIDATES, [x.to_dict() for x in cands])  # type: ignore[attr-defined]
                    # promote through the same gate that a vault write uses
                    if scope is Scope.USER and not self.is_user_memory_enabled(user_id):
                        return "refused", None
                    if scope in {Scope.PROJECT, Scope.DOMAIN} and not self.is_project_memory_enabled():
                        return "refused", None
                    item = (await self._write_user(user_id, c.text, c.kind, c.source) if scope is Scope.USER
                            else await self._write_project(c.text, c.kind, c.source, scope))
                    return ("stored", item) if item else ("skipped", None)
                await self._store.set(_NS_CANDIDATES, [x.to_dict() for x in cands])  # type: ignore[attr-defined]
                return "candidate", c
        new = MemoryItem(text=text, scope=scope, kind=kind, user_id=user_id, source=source, confidence=0.4)
        cands.append(new)
        await self._store.set(_NS_CANDIDATES, [x.to_dict() for x in cands[-200:]])  # type: ignore[attr-defined]
        return "candidate", new

    # ---- vault writes ------------------------------------------------------
    async def _write_user(self, user_id: int, text: str, kind: str, source: str) -> MemoryItem | None:
        table = dict(self._store.get(_NS_USER, {}) or {})  # type: ignore[attr-defined]
        items = [MemoryItem.from_dict(i) for i in table.get(str(user_id), [])]
        if any(i.text.lower() == text.lower() for i in items):
            return None
        item = MemoryItem(text=text, scope=Scope.USER, kind=kind, user_id=user_id, source=source)
        items.append(item)
        table[str(user_id)] = [i.to_dict() for i in items[-getattr(config, "MEMORY_USER_MAX", 40):]]
        await self._store.set(_NS_USER, table)  # type: ignore[attr-defined]
        return item

    async def _write_project(self, text: str, kind: str, source: str, scope: Scope) -> MemoryItem | None:
        items = [MemoryItem.from_dict(i) for i in (self._store.get(_NS_PROJECT, []) or [])]  # type: ignore[attr-defined]
        if any(i.text.lower() == text.lower() for i in items):
            return None
        item = MemoryItem(text=text, scope=scope, kind=kind, source=source, confidence=0.6)
        items.append(item)
        await self._store.set(_NS_PROJECT, [i.to_dict() for i in items[-getattr(config, "MEMORY_PROJECT_MAX", 200):]])  # type: ignore[attr-defined]
        return item

    # ---- retrieval (relevance-based, §46) ---------------------------------
    def user_items(self, user_id: int) -> list[MemoryItem]:
        table = self._store.get(_NS_USER, {}) or {}  # type: ignore[attr-defined]
        return [MemoryItem.from_dict(i) for i in table.get(str(user_id), [])]

    def project_items(self) -> list[MemoryItem]:
        return [MemoryItem.from_dict(i) for i in (self._store.get(_NS_PROJECT, []) or [])]  # type: ignore[attr-defined]

    def retrieve_user(self, user_id: int, query: str, limit: int = 6) -> list[str]:
        return self._rank(self.user_items(user_id), query, limit)

    def retrieve_project(self, query: str, limit: int = 5) -> list[str]:
        if not self.is_project_memory_enabled():
            return []
        return self._rank(self.project_items(), query, limit)

    @staticmethod
    def _rank(items: list[MemoryItem], query: str, limit: int) -> list[str]:
        q = _tokens(query)
        if not items:
            return []
        if not q:  # no query terms → most recent
            return [i.text for i in sorted(items, key=lambda x: -x.updated_at)[:limit]]
        scored = []
        for i in items:
            overlap = len(q & _tokens(i.text))
            if overlap:
                scored.append((overlap * (0.5 + i.confidence), i))
        scored.sort(key=lambda t: (-t[0], -t[1].updated_at))
        return [i.text for _s, i in scored[:limit]]

    # ---- user controls -----------------------------------------------------
    async def forget_user(self, user_id: int) -> bool:
        table = dict(self._store.get(_NS_USER, {}) or {})  # type: ignore[attr-defined]
        existed = str(user_id) in table
        table.pop(str(user_id), None)
        # also drop that user's pending candidates
        cands = [c for c in (self._store.get(_NS_CANDIDATES, []) or []) if c.get("user_id") != user_id]  # type: ignore[attr-defined]
        await self._store.set(_NS_USER, table)  # type: ignore[attr-defined]
        await self._store.set(_NS_CANDIDATES, cands)  # type: ignore[attr-defined]
        return existed

    def candidate_count(self) -> int:
        return len(self._store.get(_NS_CANDIDATES, []) or [])  # type: ignore[attr-defined]
