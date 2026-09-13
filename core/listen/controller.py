"""ListenController — deterministic, store-backed orchestration for one guild.

Owns sessions, devices, an append-only event log, transcripts, retention, and
deterministic search. It does NOT capture or transcribe audio itself — a capture
client ingests transcripts/events through `ingest_*`, and transcription is done by
whatever engine is registered (null by default → nothing fabricated).

Persistence reuses the Discord-backed JSON store (sync get / async set).
"""
from __future__ import annotations

import re
import time

from core.listen.devices import Device
from core.listen.events import Event, EntityType
from core.listen.retention import RetentionPolicy, deletion_audit
from core.listen.session import Session, SessionState, apply_transition, TransitionError

_NS_SESSIONS = "listen_sessions"      # {session_id: session_dict}
_NS_EVENTS = "listen_events"          # [event_dict, ...]  (append-only, capped)
_NS_TRANSCRIPTS = "listen_transcripts"  # [transcript_dict, ...]
_NS_DEVICES = "listen_devices"        # {device_id: device_dict}
_NS_RETENTION = "listen_retention"    # policy_dict

_MAX_EVENTS = 5000
_MAX_TRANSCRIPTS = 20000
_WORD = re.compile(r"[a-z0-9']+")


class ListenController:
    def __init__(self, store: object) -> None:
        self._store = store

    # ---- retention policy --------------------------------------------------
    def policy(self) -> RetentionPolicy:
        return RetentionPolicy.from_dict(self._store.get(_NS_RETENTION, {}) or {})  # type: ignore[attr-defined]

    async def set_policy(self, policy: RetentionPolicy) -> None:
        await self._store.set(_NS_RETENTION, policy.to_dict())  # type: ignore[attr-defined]

    # ---- events (append-only audit/event log) -----------------------------
    async def record_event(self, event: Event) -> Event:
        log = list(self._store.get(_NS_EVENTS, []) or [])  # type: ignore[attr-defined]
        log.append(event.to_dict())
        await self._store.set(_NS_EVENTS, log[-_MAX_EVENTS:])  # type: ignore[attr-defined]
        return event

    def events(self, *, session_id: str = "", event_type: str = "", limit: int = 50) -> list[Event]:
        out = [Event.from_dict(e) for e in (self._store.get(_NS_EVENTS, []) or [])]  # type: ignore[attr-defined]
        if session_id:
            out = [e for e in out if e.session_id == session_id]
        if event_type:
            out = [e for e in out if e.event_type == event_type]
        return out[-limit:]

    # ---- sessions ----------------------------------------------------------
    def _sessions(self) -> dict:
        return dict(self._store.get(_NS_SESSIONS, {}) or {})  # type: ignore[attr-defined]

    def get_session(self, session_id: str) -> Session | None:
        raw = self._sessions().get(session_id)
        return Session.from_dict(raw) if raw else None

    def active_session_for(self, user_id: int) -> Session | None:
        for raw in self._sessions().values():
            s = Session.from_dict(raw)
            if s.user_id == user_id and s.state not in {SessionState.COMPLETED, SessionState.FAILED}:
                return s
        return None

    async def _save_session(self, session: Session) -> None:
        table = self._sessions()
        table[session.id] = session.to_dict()
        await self._store.set(_NS_SESSIONS, table)  # type: ignore[attr-defined]

    async def create_session(self, user_id: int, *, audio_source: str = "microphone") -> Session:
        s = Session(user_id=user_id, audio_source=audio_source)
        await self._save_session(s)
        await self.record_event(Event(event_type="session_created", session_id=s.id,
                                       actor=str(user_id), state_after=str(s.state)))
        return s

    async def _transition(self, session: Session, target: SessionState, *, reason: str = "",
                          actor: str = "", event_type: str = "") -> Session:
        before = str(session.state)
        apply_transition(session, target, reason=reason)   # raises TransitionError if illegal
        await self._save_session(session)
        await self.record_event(Event(
            event_type=event_type or f"session_{target}", session_id=session.id,
            actor=actor or str(session.user_id), state_before=before, state_after=str(session.state)))
        return session

    async def acknowledge_consent(self, session: Session) -> Session:
        session.consent_ack = True
        await self._save_session(session)
        await self.record_event(Event(event_type="consent_acknowledged", session_id=session.id,
                                       actor=str(session.user_id)))
        return session

    async def authorize(self, session: Session, device_id: str = "", client: str = "") -> Session:
        session.device_id = device_id or session.device_id
        session.capture_client = client or session.capture_client
        return await self._transition(session, SessionState.AUTHORIZED, event_type="session_authorized")

    async def activate(self, session: Session) -> Session:
        # apply_transition enforces the consent gate before ACTIVE
        return await self._transition(session, SessionState.ACTIVE, event_type="capture_started")

    async def pause(self, session: Session) -> Session:
        return await self._transition(session, SessionState.PAUSED, event_type="capture_paused")

    async def resume(self, session: Session) -> Session:
        return await self._transition(session, SessionState.ACTIVE, event_type="capture_resumed")

    async def stop(self, session: Session, reason: str = "user_stop") -> Session:
        if session.state not in {SessionState.ENDING}:
            session = await self._transition(session, SessionState.ENDING, reason=reason,
                                              event_type="session_ending")
        return await self._transition(session, SessionState.COMPLETED, reason=reason,
                                      event_type="session_completed")

    async def fail(self, session: Session, reason: str) -> Session:
        return await self._transition(session, SessionState.FAILED, reason=reason,
                                      event_type="session_failed")

    # ---- devices -----------------------------------------------------------
    async def upsert_device(self, device: Device) -> None:
        table = dict(self._store.get(_NS_DEVICES, {}) or {})  # type: ignore[attr-defined]
        table[device.device_id] = device.to_dict()
        await self._store.set(_NS_DEVICES, table)  # type: ignore[attr-defined]

    def devices(self) -> list[Device]:
        return [Device.from_dict(d) for d in (self._store.get(_NS_DEVICES, {}) or {}).values()]  # type: ignore[attr-defined]

    # ---- transcripts (ingested from a capture client + engine) -------------
    async def ingest_transcript(self, transcript: dict) -> None:
        """Store a transcript event produced by a registered engine. Callers pass
        epistemic-classified fields; nothing is fabricated here."""
        rows = list(self._store.get(_NS_TRANSCRIPTS, []) or [])  # type: ignore[attr-defined]
        transcript.setdefault("id", f"tr_{int(time.time()*1000)}_{len(rows)}")
        transcript.setdefault("ts", int(time.time()))
        rows.append(transcript)
        await self._store.set(_NS_TRANSCRIPTS, rows[-_MAX_TRANSCRIPTS:])  # type: ignore[attr-defined]

    def transcripts(self) -> list[dict]:
        return list(self._store.get(_NS_TRANSCRIPTS, []) or [])  # type: ignore[attr-defined]

    # ---- deterministic search (§29/§30) -----------------------------------
    def search(self, query: str = "", *, speaker: str = "", session_id: str = "",
               date: str = "", limit: int = 10) -> list[dict]:
        """Substring/keyword search over stored transcripts with optional filters.
        Fully deterministic; returns [] when there's nothing captured yet."""
        rows = self.transcripts()
        terms = {w for w in _WORD.findall(query.lower())}
        out = []
        for r in rows:
            text = str(r.get("text", "")).lower()
            if terms and not all(t in text for t in terms):
                continue
            if speaker and r.get("speaker_id") != speaker:
                continue
            if session_id and r.get("session_id") != session_id:
                continue
            if date:
                day = time.strftime("%Y-%m-%d", time.gmtime(int(r.get("ts", 0))))
                if day != date:
                    continue
            out.append(r)
        return out[-limit:]

    # ---- retention sweep ---------------------------------------------------
    async def purge_expired(self) -> list[dict]:
        """Delete transcripts past the retention limit, emitting deletion audit
        events that never contain the deleted content."""
        pol = self.policy()
        now = int(time.time())
        rows = self.transcripts()
        kept, deleted = [], []
        for r in rows:
            if pol.is_expired("transcript", int(r.get("ts", now)), now):
                audit = deletion_audit("transcript", str(r.get("id", "?")))
                await self.record_event(Event(
                    event_type=audit["event_type"], session_id=r.get("session_id", ""),
                    actor="retention", outputs={"item_id": audit["item_id"], "reason": audit["reason"]}))
                deleted.append(audit)
            else:
                kept.append(r)
        if deleted:
            await self._store.set(_NS_TRANSCRIPTS, kept)  # type: ignore[attr-defined]
        return deleted

    async def delete_session_data(self, session_id: str) -> int:
        """Hard-delete a session's transcripts (right to erasure), with audit."""
        rows = self.transcripts()
        kept = [r for r in rows if r.get("session_id") != session_id]
        removed = len(rows) - len(kept)
        if removed:
            await self._store.set(_NS_TRANSCRIPTS, kept)  # type: ignore[attr-defined]
            await self.record_event(Event(event_type="data_deleted", session_id=session_id,
                                           actor="user", outputs={"deleted_transcripts": removed}))
        return removed
