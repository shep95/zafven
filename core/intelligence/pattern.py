"""The Universal Pattern Object + its lifecycle, provenance, and relationships.

A pattern here is a reusable problem-solving STRUCTURE — a reasoning move, a
debugging procedure, a conversation shape, a writing approach — not a saved prompt
and not a software design pattern only (§10, §17, §44). It carries:

  • a mechanism (what it actually does),
  • provenance (where it came from — never lost, §17),
  • evidence + confidence (so a hypothesis is never mistaken for a fact, §18),
  • a lifecycle status (a novel pattern is a CANDIDATE, not truth, §13/§18),
  • graph relationships to other patterns (§19),
  • and failure knowledge (a failed pattern keeps WHY it failed, §18).

Patterns are plain dataclasses so they serialize straight to the Discord-backed
JSON store. `PatternStatus` is the lifecycle; `Relation` is the edge vocabulary.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict

from core.intelligence.scope import Scope, parse as parse_scope


class PatternStatus(enum.Enum):
    """Lifecycle states (§18). A pattern climbs OBSERVED→…→ACTIVE only by earning
    evidence; it can fall to FAILED/SUPERSEDED/ARCHIVED. Nothing starts ACTIVE."""
    OBSERVED = "observed"      # noticed once, not yet formalized
    CANDIDATE = "candidate"    # formalized hypothesis, untested
    TESTING = "testing"        # being validated
    VALIDATED = "validated"    # passed validation, not yet promoted to active use
    ACTIVE = "active"          # in use for retrieval/application
    REFINED = "refined"        # a newer version exists but this is still active
    SUPERSEDED = "superseded"  # replaced by a newer version/pattern
    FAILED = "failed"          # tried and did not work — kept for its failure knowledge
    ARCHIVED = "archived"      # retired from use, preserved for history

    def __str__(self) -> str:
        return self.value


# States a pattern may be RETRIEVED for active application. A CANDIDATE/TESTING
# pattern can be *considered* but is never applied as established truth.
APPLICABLE = {PatternStatus.VALIDATED, PatternStatus.ACTIVE, PatternStatus.REFINED}


class Relation(enum.Enum):
    """Edge vocabulary for the pattern graph (§19). The registry stores edges so the
    library is a graph, not a flat list."""
    DERIVED_FROM = "derived_from"
    ANALOGOUS_TO = "analogous_to"
    COMPATIBLE_WITH = "compatible_with"
    CONFLICTS_WITH = "conflicts_with"
    SPECIALIZES = "specializes"
    GENERALIZES = "generalizes"
    REPAIRS = "repairs"
    SUPERSEDES = "supersedes"
    TESTED_BY = "tested_by"
    FAILS_UNDER = "fails_under"
    TRANSFERS_TO = "transfers_to"

    def __str__(self) -> str:
        return self.value


class Source(enum.Enum):
    """Provenance — where a pattern came from. Never lost on serialization (§17)."""
    BUILT_IN = "built_in"
    USER_FEEDBACK = "user_feedback"
    CONVERSATION = "conversation"
    PROJECT_OBSERVATION = "project_observation"
    RESEARCH = "research"
    EXPERIMENT = "experiment"
    PATTERN_COMPOSITION = "pattern_composition"
    GLOBAL_PROMOTION = "global_promotion"

    def __str__(self) -> str:
        return self.value


def _new_id() -> str:
    return "pat_" + uuid.uuid4().hex[:12]


@dataclass
class Pattern:
    """One reusable problem-solving structure. Fields mirror the spec's Universal
    Pattern Object (§17); optional ones default empty so partial patterns are valid."""
    name: str
    mechanism: str                       # what the pattern actually DOES (the core)
    id: str = field(default_factory=_new_id)
    description: str = ""

    # placement
    domain: str = "general"
    subdomain: str = ""
    family: str = ""
    abstraction_level: str = "mechanism"  # surface | mechanism | meta
    scope: Scope = Scope.PROJECT

    # applicability
    trigger: str = ""                    # when this pattern is relevant
    inputs: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    procedure: list[str] = field(default_factory=list)  # ordered steps
    constraints: list[str] = field(default_factory=list)
    expected_output: str = ""

    # relationships (denormalized ids; the registry owns the authoritative graph)
    compatible_patterns: list[str] = field(default_factory=list)
    conflicting_patterns: list[str] = field(default_factory=list)

    # failure knowledge (§18)
    failure_modes: list[str] = field(default_factory=list)
    works_when: str = ""
    fails_under: str = ""
    repair_patterns: list[str] = field(default_factory=list)

    # evidence + confidence (§18/§47) — hypothesis is not fact
    evidence: list[str] = field(default_factory=list)
    evidence_quality: str = "weak"       # weak | moderate | strong
    confidence: float = 0.2              # 0..1
    success_count: int = 0
    failure_count: int = 0
    contexts_used: list[str] = field(default_factory=list)

    # lifecycle + provenance
    status: PatternStatus = PatternStatus.CANDIDATE
    source: Source = Source.CONVERSATION
    version: int = 1
    supersedes_version_of: str = ""      # pattern id this version replaces

    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    # ---- serialization (enums <-> strings so the JSON store round-trips) ----
    def to_dict(self) -> dict:
        d = asdict(self)
        d["scope"] = str(self.scope)
        d["status"] = str(self.status)
        d["source"] = str(self.source)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        d = dict(d)
        d["scope"] = parse_scope(d.get("scope"), Scope.PROJECT)
        d["status"] = _parse_status(d.get("status"))
        d["source"] = _parse_source(d.get("source"))
        # tolerate unknown/missing keys from older stored versions
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def touch(self) -> None:
        self.updated_at = int(time.time())

    def record_outcome(self, success: bool, context: str = "") -> None:
        """Fold one real-world outcome into the pattern's evidence + confidence.
        Confidence is a smoothed success rate, so one datapoint never flips it to
        certainty (§47: preserve uncertainty; evidence accrues)."""
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        if context and context not in self.contexts_used:
            self.contexts_used.append(context)
            self.contexts_used = self.contexts_used[-20:]
        total = self.success_count + self.failure_count
        # Laplace-smoothed rate: starts near 0.5-ish, needs repeated evidence to move.
        self.confidence = round((self.success_count + 1) / (total + 2), 3)
        self.evidence_quality = "strong" if total >= 6 else "moderate" if total >= 3 else "weak"
        self.touch()

    def is_applicable(self) -> bool:
        return self.status in APPLICABLE


def _parse_status(value: object) -> PatternStatus:
    if isinstance(value, PatternStatus):
        return value
    try:
        return PatternStatus(str(value).strip().lower())
    except (ValueError, AttributeError):
        return PatternStatus.CANDIDATE


def _parse_source(value: object) -> Source:
    if isinstance(value, Source):
        return value
    try:
        return Source(str(value).strip().lower())
    except (ValueError, AttributeError):
        return Source.CONVERSATION
