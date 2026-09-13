"""Event model (§32–33) — the platform is event-oriented.

Every meaningful thing that happens (a session start, a device change, a transcript,
an environment sound, a deletion, a security event) is an immutable, timestamped,
provenance-carrying Event. Events are deterministic records; probabilistic content
inside them (a transcript, a classification) is carried as epistemic Claims so a
FACT is never confused with an ESTIMATE.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict


class EntityType(enum.Enum):
    USER = "user"
    SESSION = "session"
    DEVICE = "device"
    AUDIO_SEGMENT = "audio_segment"
    AUDIO_EVENT = "audio_event"
    SPEAKER = "speaker"
    SPEAKER_PROFILE = "speaker_profile"
    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"
    LANGUAGE_EVENT = "language_event"
    ENVIRONMENT_EVENT = "environment_event"
    ACOUSTIC_EVENT = "acoustic_event"
    CONVERSATION = "conversation"
    CONVERSATION_TURN = "conversation_turn"
    PATTERN = "pattern"
    AUDIT_EVENT = "audit_event"
    PERMISSION = "permission"
    RETENTION_POLICY = "retention_policy"
    IDENTITY_ASSOCIATION = "identity_association"
    PROVENANCE_RECORD = "provenance_record"
    SECURITY_EVENT = "security_event"

    def __str__(self) -> str:
        return self.value


def _new_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Event:
    """The universal event structure (§33). Timestamps are epoch-ms captured
    deterministically; corrected timestamps never overwrite originals (§58)."""
    event_type: str
    event_id: str = field(default_factory=lambda: _new_id("evt"))
    timestamp_start: int = field(default_factory=lambda: int(time.time() * 1000))
    timestamp_end: int | None = None
    timestamp_corrected: int | None = None      # never overwrites timestamp_start (§58)
    correction_reason: str = ""
    source: str = ""
    session_id: str = ""
    device_id: str = ""
    actor: str = ""                              # who/what caused it
    state_before: str = ""
    state_after: str = ""
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    confidence: float | None = None
    epistemic: str = "observation"
    evidence: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)  # ordered pipeline lineage
    classification: str = ""
    retention_policy: str = "default"
    permissions: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)
    parent_event: str = ""
    child_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def correct_timestamp(self, corrected_ms: int, reason: str) -> None:
        """Record a corrected timestamp WITHOUT destroying the original (§58)."""
        self.timestamp_corrected = corrected_ms
        self.correction_reason = reason
