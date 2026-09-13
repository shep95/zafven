"""Epistemic classification (§5) — never blur a fact with an estimate.

Every important value the platform records carries an epistemic class. A measured
fundamental frequency is an OBSERVATION; a voice-based age band is an ESTIMATE; the
person's real age is UNKNOWN. The system never silently promotes one class into a
stronger one, so nothing probabilistic is ever presented as established fact.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Epistemic(enum.Enum):
    OBSERVATION = "observation"      # directly captured/measured
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"
    INFERENCE = "inference"
    ESTIMATE = "estimate"            # probabilistic model output
    FACT = "fact"                    # independently verified
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


# Classes that may NOT be auto-upgraded into. FACT specifically requires independent
# verification — a model can never mint a FACT on its own (that's the core §5 rule).
_UPGRADE_FORBIDDEN = {Epistemic.FACT}


@dataclass
class Claim:
    """A value plus how we know it. Confidence is only meaningful for probabilistic
    classes; for OBSERVATION it's the measurement, for UNKNOWN it's absent."""
    value: object
    epistemic: Epistemic = Epistemic.UNKNOWN
    confidence: float | None = None
    evidence: list[str] = field(default_factory=list)
    method: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "epistemic": str(self.epistemic),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        try:
            ep = Epistemic(str(d.get("epistemic", "unknown")).lower())
        except ValueError:
            ep = Epistemic.UNKNOWN
        return cls(value=d.get("value"), epistemic=ep, confidence=d.get("confidence"),
                   evidence=list(d.get("evidence", []) or []), method=d.get("method", ""))


def observation(value, *, method: str = "", evidence: list[str] | None = None) -> Claim:
    return Claim(value, Epistemic.OBSERVATION, confidence=None, method=method, evidence=evidence or [])


def estimate(value, confidence: float, *, method: str = "", evidence: list[str] | None = None) -> Claim:
    return Claim(value, Epistemic.ESTIMATE, confidence=confidence, method=method, evidence=evidence or [])


def unknown(reason: str = "") -> Claim:
    return Claim(None, Epistemic.UNKNOWN, method=reason)


def can_upgrade(current: Epistemic, target: Epistemic) -> bool:
    """A value may only become a FACT through explicit independent verification —
    never automatically. All other reclassifications must still be explicit, but this
    guard is the hard one the spec insists on (§5/§19 self-reported identity)."""
    if target in _UPGRADE_FORBIDDEN:
        return False
    return True
