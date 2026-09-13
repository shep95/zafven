"""Retention + deletion (§37) — deterministic, auditable, and content-destroying.

A retention policy says how long each data class is kept. Expiry is computed
deterministically from timestamps. Deletion removes the content and emits an audit
event that records THAT a deletion happened WITHOUT retaining the deleted content.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict

# 0 means "never retain" (delete immediately-eligible); -1 means "retain indefinitely".
NEVER = 0
FOREVER = -1


@dataclass
class RetentionPolicy:
    name: str = "default"
    raw_audio_seconds: int = 3600       # keep raw audio 1h by default
    transcript_seconds: int = 30 * 86400
    metadata_seconds: int = 90 * 86400

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RetentionPolicy":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    def _limit_for(self, data_class: str) -> int:
        return {
            "raw_audio": self.raw_audio_seconds,
            "transcript": self.transcript_seconds,
            "metadata": self.metadata_seconds,
        }.get(data_class, self.metadata_seconds)

    def is_expired(self, data_class: str, created_at: int, now: int | None = None) -> bool:
        limit = self._limit_for(data_class)
        if limit == FOREVER:
            return False
        if limit == NEVER:
            return True
        now = now if now is not None else int(time.time())
        return (now - int(created_at)) >= limit


def deletion_audit(data_class: str, item_id: str, reason: str = "retention") -> dict:
    """Record of a deletion that does NOT include the deleted content itself."""
    return {
        "event_type": "audio_deleted" if data_class == "raw_audio" else "data_deleted",
        "data_class": data_class,
        "item_id": item_id,           # id/reference only — never the content
        "reason": reason,
        "ts": int(time.time()),
    }
