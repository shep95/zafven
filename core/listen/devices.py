"""Device model (§9) — deterministic representation of capture devices.

Actual device enumeration and capture happen in the external capture client (a bot
cannot read your microphone). This layer records what the client reports, tracks
device state transitions, and notes the exact point a device changed mid-session.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field, asdict


class DeviceState(enum.Enum):
    AVAILABLE = "available"
    SELECTED = "selected"
    CAPTURING = "capturing"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    UNAVAILABLE = "unavailable"
    PERMISSION_DENIED = "permission_denied"
    UNSUPPORTED = "unsupported"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


@dataclass
class Device:
    device_id: str
    name: str = ""
    manufacturer: str = ""
    type: str = ""                    # builtin_mic | usb_mic | bluetooth | interface | system_audio | virtual
    connection: str = ""              # wired | usb | bluetooth | virtual | system
    bluetooth_id: str = ""
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""
    capabilities: list[str] = field(default_factory=list)
    permission_status: str = "unknown"
    state: DeviceState = DeviceState.AVAILABLE
    connection_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = str(self.state)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Device":
        d = dict(d)
        try:
            d["state"] = DeviceState(str(d.get("state", "available")).lower())
        except ValueError:
            d["state"] = DeviceState.AVAILABLE
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def set_state(self, state: DeviceState, note: str = "") -> None:
        self.connection_history.append({"ts": int(time.time()), "state": str(state), "note": note})
        self.connection_history = self.connection_history[-50:]
        self.state = state
