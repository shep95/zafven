# Asherin Adaptive Intelligence — architecture + requirement traceability

This document maps the master implementation spec onto what was actually built in
zafven, and states honestly what is fully implemented, what is adapted to a Discord
bot, and what a single-instance bot genuinely cannot do the spec's way.

## Core principle (§5)

The model is a **replaceable capability**, not the intelligence. Asherin owns the
infrastructure around it. The runtime flow:

```
message
  → context resolver        (conversation state + user/project memory + patterns + global)
  → persona / model prompt
  → provider gateway         (built-in model OR a guild's own key)
  → reply
  → validator / critic       (instruction + preference compliance)
  → outcome
  → learning gate            (model proposes; system decides persistence)
      → candidate memory / candidate pattern
      → (monthly) abstraction → quarantine → global evaluation → global registry
```

Persistence reuses zafven's existing Discord-backed JSON store (`core/store.py`) —
no new database. Everything is **fail-open**: if a subsystem errors, chat still
works and simply loses the extra intelligence for that turn.

## Scope mapping (Discord reality)

| Spec scope   | zafven concept                     |
|--------------|------------------------------------|
| TASK         | one request                        |
| CONVERSATION | one channel/thread                 |
| PROJECT      | one guild (server)                 |
| USER         | one Discord user                   |
| DOMAIN       | a topic / brain domain             |
| GLOBAL       | cross-guild, abstracted, validated |

## Requirement → implementation traceability (§42)

Status key: **IMPLEMENTED** (real + tested) · **ADAPTED** (real, reshaped for a
Discord bot) · **PARTIAL** (interface real, bounded by host) .

| # | Requirement | Where | Test | Status |
|---|-------------|-------|------|--------|
| §5 | Model as replaceable capability under intelligence | `intelligence/__init__.py`, `gateway.py` | cog-load | IMPLEMENTED |
| §6 | Isolated, ephemeral conversation state | `context.py` | — | IMPLEMENTED |
| §7 | Memory ≠ conversation; promotion gate | `memory.py`, `context.py` | candidate test | IMPLEMENTED |
| §8 | Hard memory ON/OFF boundary | `memory.py` `set_user_memory`/`offer` | `test_memory_off_writes_nothing` | IMPLEMENTED |
| §9 | User ≠ project ≠ pattern scope, never auto-converted | `scope.py`, `memory.py` | isolation + scope tests | IMPLEMENTED |
| §10 | Pattern intelligence (not just docs); many pattern kinds | `pattern.py`, `registry.py` | pattern tests | IMPLEMENTED |
| §11/§12 | Adaptive pattern creator; feedback as learning signal | `creator.py`, `learning.py` | `test_failure_is_recorded` | IMPLEMENTED |
| §13 | UNKNOWN is a real state | `creator.assess_coverage`/`Coverage` | `test_unknown_is_a_real_state` | IMPLEMENTED |
| §14/§15 | Novel discovery + cross-domain transfer | `creator.discover` | — (LLM path) | IMPLEMENTED |
| §16 | Pattern composition | `creator.compose` | — | IMPLEMENTED |
| §17 | Universal Pattern Object + provenance | `pattern.Pattern` | roundtrip smoke | IMPLEMENTED |
| §18 | Lifecycle states + failure knowledge | `pattern.PatternStatus`, `registry.record_outcome` | `test_outcomes_promote_then_fail` | IMPLEMENTED |
| §19 | Registry is a graph | `registry` edges/`relate`/`neighbors` | versioning test | IMPLEMENTED |
| §20/§22 | Provider abstraction + capability routing | `gateway.py` | `test_capability_routing_detects_unsupported` | ADAPTED (Gemini provider; interface is provider-agnostic) |
| §21/§38 | Credential boundary; key never in prompt/pattern/memory/log | `gateway.CredentialVault` | `test_key_masked_and_not_leaked` | ADAPTED (boundary real; at-rest is base64 in the data channel, not KMS — documented, opt-in) |
| §23 | Pattern Forge above the model | orchestrator ordering in `__init__.py` | — | IMPLEMENTED |
| §24 | Critic / validator | `critic.py` (+ reuse of `gateway.council`) | — | IMPLEMENTED |
| §25 | Learning gate: model proposes, system persists | `learning.py` | memory/feedback tests | IMPLEMENTED |
| §26/§28 | Global learning: quarantine + monthly + independence | `globals.py`, `intelligence_cog` loop | `test_independence_required_for_promotion` | ADAPTED (see limitations) |
| §27 | Absolute global privacy boundary | `globals._abstract`/`_looks_personal`/`_scrub` | `test_privacy_boundary_rejects_personal` | IMPLEMENTED |
| §29/§30 | Global evaluation dimensions + layers | `globals.run_monthly_cycle`, `layer_of` | independence test | ADAPTED |
| §31 | Versioning never overwrites | `registry.new_version` | `test_versioning_never_overwrites` | IMPLEMENTED |
| §32 | Global never overrides local | `context.ResolvedContext.to_prompt` (marks scope, "prefer local") | — | IMPLEMENTED |
| §33 | Auditable monthly manifest | `globals` manifests + `/globallearn status` | independence test | IMPLEMENTED |
| §34 | Works beyond coding | domain-agnostic modules; wired into general chat | — | IMPLEMENTED |
| §35 | Shepherd as framework, not a persona | integrated as patterns/mechanisms only | — | IMPLEMENTED |
| §37 | Namespaced data isolation | per-guild store namespaces + separate creds ns | isolation tests | IMPLEMENTED |
| §39 | Management UI without exposing secrets/CoT | `cogs/intelligence_cog.py` | cog-load | IMPLEMENTED |
| §45/§46 | Infra holds intelligence; relevance retrieval | `registry.retrieve`, `memory` ranking | pattern/memory tests | IMPLEMENTED |
| §47 | Evidence-based, uncertainty preserved | `pattern.record_outcome` (smoothed confidence) | roundtrip smoke | IMPLEMENTED |
| §48 | No autonomous weight retraining claimed | pattern-level adaptation only, documented here | — | IMPLEMENTED |

## Honest limitations (§43 — not hidden)

1. **"Population" global learning = this instance's guilds only.** A single bot
   process only sees the guilds it is in, so independence analysis counts distinct
   *source guilds*, not separate deployments. True multi-deployment population
   learning would need a shared backend this bot does not have.
2. **Credential at-rest is not KMS-grade.** The credential *boundary* is real (the
   key never enters a prompt/pattern/memory/log, only `use()` yields it). But it is
   stored base64-obfuscated in the guild's hidden data channel, so user keys are
   **opt-in** (`PROVIDER_USER_KEYS_ENABLED`, default off) and should be rotated.
3. **One provider family implemented.** The gateway interface is provider-agnostic
   and capability-aware; the concrete provider is Gemini (built-in + user key).
   Adding another provider is a new `Provider` subclass, no architecture change.
4. **Discovery/abstraction quality depends on the model.** `creator` and the global
   abstraction call the model; when it's unavailable they fall back to conservative
   heuristics rather than fabricating patterns.

## Web-app spec parts with no Discord surface

The spec targets a web app (`Asherin.chat`). These parts have no equivalent in a
Discord bot and were intentionally not built: browser frontend/routing, login auth,
a projects UI, and per-request artifact panes. Their *data* analogues exist
(project = guild, conversation = channel), and the management surface is slash
commands instead of web controls.
