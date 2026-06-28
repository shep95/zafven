<div align="center">

# 🜲 zafven

**An esoteric reading engine for Discord.**
Vedic astrology · numerology · Chinese zodiac · astrological outlook · server management
Computed in code. Narrated by Gemini. Paywalled. Hosted on Railway.

<sub>Readings are for reflection & entertainment — not financial, medical, legal, or safety advice.</sub>

</div>

---

## What it is

zafven turns deterministic esoteric math into living, LLM-narrated readings. Every
number, sign, and nakshatra is **computed in Python** (Swiss Ephemeris, Pythagorean
numerology, zodiac tables); the **Gemini LLM** only *phrases* what the code already
calculated — so it can't hallucinate your chart. A truth-guard layer keeps every
reading honest and framed as entertainment, and reading commands are **paywalled**
behind a premium role or a Discord subscription.

## Architecture

```mermaid
flowchart TD
    U[User runs a slash command] --> PAY{Premium check}
    PAY -->|no access| UP[🔒 Upsell / subscribe button]
    PAY -->|has access| C{Cog}
    C --> CORE["Deterministic core<br/>(Swiss Ephemeris · numerology · zodiac · vibe stats)"]
    CORE --> FACTS[Computed facts]
    BL["Brain loader<br/>(one domain at a time)"] --> SP[System prompt]
    PER[persona.md] --> BL
    GUARD[anti_spiral.md] --> BL
    DOM["domain brain<br/>vedic / numerology / zodiac / emotions"] --> BL
    FACTS --> GW[ModelGateway]
    SP --> GW
    GW <-->|HTTPS · retry/backoff| GEM["Gemini API<br/>text · vision · Google Search grounding"]
    GW --> EMB[Discord embed reply]
    C -.no LLM.-> SRV["Server features<br/>join/leave log · inactive-kick"]
```

## A reading, step by step

```mermaid
sequenceDiagram
    actor User
    participant Discord
    participant Cog as zafven cog
    participant Core as deterministic core
    participant Brain as brain loader
    participant Gemini
    User->>Discord: /vedic 1995-08-23 14:30 28.61 77.21
    Discord->>Cog: interaction
    Cog->>Cog: premium check (role / subscription / admin)
    Cog->>Core: compute_chart(date, time, lat, lon)
    Core-->>Cog: Moon sign, nakshatra, ascendant
    Cog->>Brain: persona + anti-spiral + vedic
    Brain-->>Cog: system prompt
    Cog->>Gemini: narrate(system, facts)
    Gemini-->>Cog: reading text
    Cog-->>User: embed (with entertainment footer)
```

## The brains

Each command loads **one** knowledge module (plus the persona and the truth-guard).
They live in [`brains/`](brains/) as plain markdown and are read-only at runtime.

| Brain | Powers | Source lineage |
|---|---|---|
| `persona.md` | the zafven voice | Asher Logic / Zophiel register |
| `anti_spiral.md` | honesty guard, anti-sycophancy | Anti-Spiral Protocol |
| `vedic.md` | `/vedic`, `/predict` | Vedic planet significations, nakshatras, dashas |
| `numerology.md` | `/numerology` | Pythagorean + Vedic planet mapping |
| `zodiac.md` | `/zodiac` | Chinese zodiac physiognomy |
| `emotions.md` | `/vibe` | communication-style heuristics |

> The design deliberately loads brains **one at a time** — concatenating all of them
> produces contradictory mush.

## Commands

🔒 = premium-only (paywalled).

| Command | What it does |
|---|---|
| 🔒 `/vedic <birth_date> [time] [lat] [lon]` | Sidereal reading — Moon sign, nakshatra, ascendant |
| 🔒 `/numerology <full_name> <birth_date>` | Life path, expression, soul urge, personality, birthday |
| 🔒 `/zodiac <birth_date>` | Chinese animal + element archetype |
| 🔒 `/predict <birth_date> [focus] [chart_image]` | Astrological **outlook** — uses Gemini **Google Search** for current transits and **vision** to read an uploaded chart |
| 🔒 `/vibe [share]` | Playful read of **your own** chat style (self-only, opt-in) |
| 🔒 `/audit <file>` | Upload code or a **.zip** → narrative security + quality audit (logic / workflow / bug / security / supply-chain), then **forge the fixed code on approval** |
| `/kick_inactive [days] [dry_run] [message]` | Preview/remove inactive members + reinvite DM (**dry-run by default**, admin-gated) |
| *(automatic)* | Logs joins & leaves to `#member-log` |

## The paywall

Reading commands are gated by [`core/premium.py`](core/premium.py). A member gets
access if **any** of these holds:

1. they have a **premium role** (`PREMIUM_ROLES`, default `Premium`) — assign it
   after payment via Patreon/Ko-fi/whatever you use;
2. they hold a valid **Discord app-subscription** entitlement (`PREMIUM_SKU_ID`,
   Discord's native monetization — shows a built-in *Subscribe* button);
3. they're an **admin / guild owner** and `PREMIUM_BYPASS_ADMIN` is on (for testing).

Non-subscribers get an ephemeral upsell with a subscribe button (`SUBSCRIBE_URL`
link and/or the native premium button when a SKU is set). Server-management
commands stay admin-gated, not paywalled.

## Quick start (local)

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in DISCORD_TOKEN and GEMINI_API_KEY
python bot.py
```

Set `GUILD_ID` during development so slash commands appear instantly.
Enable **Server Members** + **Message Content** intents in the Discord Developer Portal.

## Deploy on Railway

```mermaid
flowchart LR
    GH[GitHub repo] --> RW[Railway project]
    RW --> NIX[Nixpacks build<br/>requirements.txt]
    NIX --> WORKER["worker: python bot.py"]
    ENV[Variables:<br/>DISCORD_TOKEN · GEMINI_API_KEY] --> WORKER
```

1. Push this repo to GitHub, then **New Project → Deploy from GitHub** in Railway.
2. Add Variables: `DISCORD_TOKEN`, `GEMINI_API_KEY` (+ any overrides from `.env.example`).
3. Railway reads [`railway.json`](railway.json) / [`Procfile`](Procfile) and runs the `worker` process.
4. Watch the deploy logs for `zafven online as …`.

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | — | **Required.** Bot token |
| `GEMINI_API_KEY` | — | **Required.** Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | multimodal model for readings + vision |
| `GEMINI_WEB_SEARCH` | `auto` | `auto` / `on` / `off` for `/predict` grounding |
| `PREMIUM_ROLES` | `Premium` | roles that unlock paywalled commands |
| `PREMIUM_SKU_ID` | *(blank)* | Discord monetization SKU for native subscriptions |
| `PREMIUM_BYPASS_ADMIN` | `true` | admins/owner skip the paywall |
| `SUBSCRIBE_URL` | *(blank)* | external subscribe link on the upsell |
| `GUILD_ID` | *(blank)* | restrict commands to one guild for instant sync |
| `MEMBER_LOG_CHANNEL` | `member-log` | join/leave log channel |
| `PROTECTED_ROLES` | `Admin,Moderator,Mod,Booster` | never auto-kicked |
| `DEFAULT_INACTIVE_DAYS` | `30` | inactivity threshold |
| `ACTIVITY_SCAN_LIMIT` | `2000` | messages scanned per channel |
| `JOIN_GRACE_DAYS` | `7` | new-member exemption |

## Scope & ethics

zafven was built from a large library of "brain" documents. The **astrology,
numerology, zodiac, persona, and truth-guard** material is in use. Deliberately
**excluded** by design, because they target or manipulate people rather than
entertain them:

- ❌ refusal-evasion / jailbreak scaffolding for violence or targeting
- ❌ covert psychological profiling of non-consenting third parties
- ❌ mass surveillance / psychographic manipulation / "election engineering"
- ❌ offensive hacking / breach tooling
- ❌ real death, assassination, market, or geopolitical "forecasting"

`/predict` is a **symbolic outlook**, not a forecast. The truth-guard
([`brains/anti_spiral.md`](brains/anti_spiral.md)) keeps every reading framed as a
mirror, not a prophecy.

## Project layout

```
zafven/
├── bot.py              # entry point, wires the Gemini gateway, syncs commands
├── config.py           # env-driven settings + fail-fast validation
├── brains/             # read-only knowledge modules (one per domain)
├── core/               # deterministic logic + model_gateway + brain_loader
└── cogs/               # slash commands
```
