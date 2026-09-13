# Acoustic observation platform (`/listen`) — architecture, audit, and limits

This is the architecture-first deliverable the build spec asks for (§81–84) before
production code, plus the honest limitation list (§87). It describes a **consent-first
personal audio-observation platform** — the same category as meeting recorders,
transcription tools, and body/dash cams — controlled from Discord, with the
deterministic core built in this repo and the probabilistic + capture parts isolated
as external dependencies.

> **Legal framing.** Recording your own environment is broadly lawful and often
> encouraged for personal safety; recording *other people* can require their consent
> (all-party-consent jurisdictions, GDPR, etc.). The platform is built consent-first
> — explicit activation, a required legal-notice acknowledgement, a visible recording
> indicator in the capture client, retention/deletion, and full audit — and puts
> lawful-use responsibility on the operator. It has **no covert/stealth mode**.

## 1. Layer separation (§2)

```
Discord control (this repo, deterministic)
  → session controller + state machine
  → event / audit log + provenance
  → storage (Discord-backed JSON store) + deterministic search
Capture client (SEPARATE app — external)      ← reads the mic, shows indicator
Probabilistic engines (behind interfaces)      ← ASR / diarization / translation
```

The bot never reads a microphone. It authorizes, tracks, stores, searches, and
audits; capture + inference are external and pluggable.

## 2. What is built here (deterministic, tested)

| Module | Role | Spec |
|--------|------|------|
| `core/listen/epistemic.py` | OBSERVATION…UNKNOWN classes; FACT never auto-minted | §5 |
| `core/listen/events.py` | universal Event + entity types; timestamp correction keeps original | §32,§33,§58 |
| `core/listen/session.py` | session state machine + **consent gate** before ACTIVE | §77,§36 |
| `core/listen/devices.py` | device state model + change history | §9 |
| `core/listen/retention.py` | retention policy, expiry, content-free deletion audit | §37 |
| `core/listen/interfaces.py` | isolated ML ports + **null engines that return UNKNOWN** | §4,§87 |
| `core/listen/controller.py` | store-backed sessions/events/transcripts/search/retention | §29,§30,§55 |
| `cogs/listen_cog.py` | `/listen` control surface (consent-gated) | §6 |

Tests (`scripts/smoke_test.py`): state-machine legality, consent gate, epistemic
no-auto-FACT, null-engine no-fabrication, retention expiry + deletion audit,
controller lifecycle + search + erasure, timestamp-correction preserves original.

## 3. State machines (§77)

- **Session:** CREATED → AUTHORIZED → ACTIVE ⇄ PAUSED/DEGRADED → ENDING → COMPLETED,
  with FAILED reachable from any live state. ACTIVE is unreachable without
  `consent_ack` — the hard privacy gate.
- Illegal edges raise `TransitionError`; nothing transitions implicitly.

## 4. Epistemic discipline (§5)

Every probabilistic value is a `Claim(value, epistemic, confidence, evidence, method)`.
A measured frequency is OBSERVATION; a voice age band is ESTIMATE; the real age is
UNKNOWN. `can_upgrade()` forbids auto-promotion to FACT — only independent
verification makes a FACT. Self-reported names are stored as "said their name was X",
never "is X" (§19).

## 5. Privacy, retention, audit (§36–39, §62)

Explicit activation + consent ack; per-operator scoping; configurable retention
(`/listen retention`); erasure (`/listen delete`) that emits a deletion audit event
**without** the deleted content; every state change and data action is logged
(`/listen history`). Sensitive inferences (identity/age/voice category/deception) are
either disabled or, if a future engine provides them, carried strictly as ESTIMATE
with confidence — and deception output is observations/contradictions, never "is
lying" (§69).

## 6. Model audit (§40, §83) — findings + repairs

- *False certainty* → repaired by the epistemic layer + null engines (no fabricated
  transcripts).
- *Timestamp corruption* → repaired: corrections never overwrite the original (§58).
- *Privacy leakage / silent capture* → repaired: consent gate + explicit `audio_source`
  (microphone vs system_audio), no silent system-audio capture (§8).
- *Retention violation* → repaired: deterministic expiry + auditable deletion.
- *Permission bypass* → sessions are per-operator; retention config is `manage_guild`.
- *Unreachable/duplicate states* → repaired: explicit transition graph, terminal states.

## 7. Honest limitations (§87 — stated, not hidden)

1. **The bot cannot capture your microphone.** Real capture requires a separate
   cross-platform **capture client** (Windows/macOS/Linux; iOS/Android are heavily
   restricted for background mic access). That client is not in this repo yet; the
   control layer defines its contract (authenticate → report device → ingest
   transcripts/events).
2. **No transcription without an engine.** Transcription, diarization, language ID,
   translation, and environmental classification are probabilistic and **off by
   default** (null engines). Until a real engine is registered, sessions are
   authorized and audited but produce **no transcripts** — surfaced honestly by
   `/listen status`/`transcript`, never faked.
3. **Acoustic source separation, speaker matching, age/voice-category** are
   probabilistic and, if ever enabled, remain ESTIMATES; they are not shipped on.
4. **Legal variability.** All-party-consent laws differ by jurisdiction; the platform
   provides consent affordances but cannot determine legality for the operator.
5. **Recording other Discord members in a voice channel is out of scope** — that
   would need all-party consent and is a different design; `/listen` is the operator
   recording their own authorized device.

## 8. Roadmap to a fuller build (§81)

Done: control layer, state machines, epistemic model, event/audit, retention,
deterministic search, isolated engine interfaces. Next, in order: the capture-client
app + ingest API; a registered ASR/diarization engine; the frontend dashboard/timeline;
the adaptive pattern layer over acoustic/conversation events (the intelligence layer
in `core/intelligence/` already provides the pattern registry + lifecycle to build on).
