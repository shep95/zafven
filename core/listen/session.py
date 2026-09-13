"""Session + system state machines (§77) and the deterministic session controller.

All transitions are explicit and validated — no state is reachable except through a
defined edge. A session cannot become ACTIVE (capturing) until the operator has
acknowledged the consent + legal notice, which enforces the spec's privacy-first
requirement (§36) and the real-world rule that recording others may require consent.

This layer is fully deterministic and store-backed. It does not itself capture audio
(that's the external capture client); it authorizes, tracks, and audits sessions.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict


class SessionState(enum.Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    PAUSED = "paused"
    DEGRADED = "degraded"
    ENDING = "ending"
    COMPLETED = "completed"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


# Explicit transition graph (§77). Anything not listed is rejected.
_SESSION_EDGES: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {SessionState.AUTHORIZED, SessionState.FAILED},
    SessionState.AUTHORIZED: {SessionState.ACTIVE, SessionState.FAILED, SessionState.ENDING},
    SessionState.ACTIVE: {SessionState.PAUSED, SessionState.DEGRADED, SessionState.ENDING, SessionState.FAILED},
    SessionState.PAUSED: {SessionState.ACTIVE, SessionState.ENDING, SessionState.FAILED},
    SessionState.DEGRADED: {SessionState.ACTIVE, SessionState.PAUSED, SessionState.ENDING, SessionState.FAILED},
    SessionState.ENDING: {SessionState.COMPLETED, SessionState.FAILED},
    SessionState.COMPLETED: set(),
    SessionState.FAILED: set(),
}


def can_transition(current: SessionState, target: SessionState) -> bool:
    return target in _SESSION_EDGES.get(current, set())


TERMINAL = {SessionState.COMPLETED, SessionState.FAILED}


@dataclass
class Session:
    user_id: int
    id: str = field(default_factory=lambda: "session_" + uuid.uuid4().hex[:10])
    state: SessionState = SessionState.CREATED
    device_id: str = ""
    consent_ack: bool = False               # operator acknowledged consent + legal notice
    audio_source: str = "microphone"        # microphone | system_audio (never silent, §8)
    created_at: int = field(default_factory=lambda: int(time.time()))
    authorized_at: int = 0
    started_at: int = 0
    ended_at: int = 0
    retention_policy: str = "default"
    capture_client: str = ""                # id/label of the external capture client, if connected
    end_reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = str(self.state)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        d = dict(d)
        try:
            d["state"] = SessionState(str(d.get("state", "created")).lower())
        except ValueError:
            d["state"] = SessionState.CREATED
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def duration_seconds(self) -> int:
        if not self.started_at:
            return 0
        end = self.ended_at or int(time.time())
        return max(0, end - self.started_at)


class TransitionError(RuntimeError):
    pass


def apply_transition(session: Session, target: SessionState, *, reason: str = "") -> Session:
    """Move a session to `target` if the edge is legal, else raise. Enforces the
    consent gate: a session may only go ACTIVE after consent is acknowledged."""
    if not can_transition(session.state, target):
        raise TransitionError(f"illegal transition {session.state} → {target}")
    if target is SessionState.ACTIVE and not session.consent_ack:
        raise TransitionError("cannot start capture before consent is acknowledged")
    now = int(time.time())
    if target is SessionState.AUTHORIZED:
        session.authorized_at = now
    elif target is SessionState.ACTIVE and not session.started_at:
        session.started_at = now
    elif target in TERMINAL:
        session.ended_at = now
        session.end_reason = reason
    session.state = target
    return session
