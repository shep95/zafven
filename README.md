<div align="center">

# 🜲 zafven

**An esoteric reading engine for Discord.**
Vedic astrology · numerology · Chinese zodiac · astrological outlook · server management
Computed in code. Narrated by Gemini. Hosted on Railway.

<sub>Readings are for reflection & entertainment — not financial, medical, legal, or safety advice.</sub>

</div>

---

## What it is

zafven turns deterministic esoteric math into living, LLM-narrated readings. Every
number, sign, and nakshatra is **computed in Python** (Swiss Ephemeris, Pythagorean
numerology, zodiac tables); the **Gemini LLM** only *phrases* what the code already
calculated — so it can't hallucinate your chart. A truth-guard layer keeps every
reading honest and framed as entertainment.

## Architecture

```mermaid
flowchart TD
    U[User runs a slash command] --> C{Cog}
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

| Command | What it does |
|---|---|
| `/vedic <birth_date> <birth_time> <birth_place>` | **Full** sidereal chart — geocodes the birthplace → timezone → UTC, computes ascendant, Moon + nakshatra/pada, Sun, and current **Vimshottari Mahādashā/Antardashā** |
| `/numerology <full_name> <birth_date>` | Full reading on **both** solar & Chinese-lunar birthday — driver, life path, month, year, expression, soul urge, personality, maturity + planet rulers |
| `/zodiac <birth_date>` | Chinese zodiac — **year + month + day** animals from your lunar birthday |
| `/predict <question> [birth_date]` | **Ask-anything oracle** — Gemini **Google Search** for current real context + an astrological lens (entertainment; no financial/price forecasts) |
| `/vibe [share]` | Playful read of **your own** chat style (self-only, opt-in) |
| `/profile <member>` | **Public** communication-style read of a member (surface vibe, **not** psychology; opt-out via the `no-readings` role) |
| `/imagine <image> [question]` | Gemini-vision **describe & interpret** an uploaded image (no people-ID, no geolocation) |
| `/synastry <name_a> <date_a> <name_b> <date_b>` | Compatibility reading (numerology + Chinese-zodiac scoring, narrated) |
| `/tarot [question] [cards]` · `/iching [question]` · `/dream <dream>` | Tarot spread, I Ching cast, symbolic dream reading |
| `/gematria decode\|date\|resonance <word>` | 5-cipher gematria — Chaldean, elemental signature, soul/personality, trigger numbers, date sync, resonance |
| `/sigil <intent>` · `/portrait <name> <date>` | **Generated art** — a personal sigil / numerology frequency portrait (PNG) |
| `/research <topic>` · `/tldr [count]` · `/askdoc <pdf> <q>` | Live web-research briefing · channel summary · ask a PDF |
| `/youtube <query>` | Find YouTube videos (verified links with `YOUTUBE_API_KEY`, else AI-suggested) |
| `/grab <link> [spoiler]` | Pull the **image/video** from a link (direct file or page preview media) and re-upload it here — SSRF-guarded, size-capped; not a platform ripper |
| `/learn <topic \| youtube link>` | Builds a **knowledge report** (web-researched, or from a video transcript) and posts it to a public **#knowledge** channel for friends to learn |
| `/audit <file>` | Upload code or a **.zip** → narrative security + quality audit (logic / workflow / bug / security / supply-chain), then **forge the fixed code on approval** |
| `/forge <spec> [language]` | Describe a feature → design narrative → **forge the code on approval** |
| `/rank [member]` · `/leaderboard` | Initiation XP & levels — earn roles by chatting |
| `/capsule <message> <deliver_on> [public]` | **Time capsule** — delivered on a future date |
| `/mood` | Aggregate read of the server's current vibe (no individuals named) |
| `/cipher` (mod) · `/solve <answer>` | Cipher-puzzle events — first to solve wins |
| *(daily/weekly)* | A **transit + koan** posts to `#oracle` daily; a weekly **egregore digest** on Mondays |
| `/report <message_link> [reason]` | Escalate a message to mods — forwards it to `#mod-alerts` and **@mentions the mod role** |
| `/kick_inactive [days] [dry_run] [message]` | Preview/remove inactive members + reinvite DM (**dry-run by default**, admin-gated) |
| *(chat)* | **@mention or reply to Zafven to ask her anything** — she answers questions (with web look-up when needed), jokes (real comedy engine), and banters, in character (she/her). She has **live moods** (joy/affection/anger/fear/pride that shift with how you treat her — `/feelings`) and **remembers** what you tell her (`/memory`, `/forget`) |
| `/persona set\|view\|reset` | **Admins reshape how she acts** (tone/length/formality) — adapts her to the server; safety boundaries stay locked |
| *(automatic)* | **Welcome card**, leave log, deleted-message log, curse-word censor, anti-spam/scam, anti-cyberbullying, anti-manipulation, **file/image safety scan (NSFW + malware)** |

## Moderation: welcome, anti-spam, profanity

- **Welcome card** ([`cogs/logging_cog.py`](cogs/logging_cog.py)) — posts a rich
  embed to `#welcome` on join (username, ID, account age, join time, member #).
  Leaves are logged to `#member-log`. Both channels auto-create if missing.
- **Deleted-message log** ([`cogs/messagelog_cog.py`](cogs/messagelog_cog.py)) —
  posts every deleted message to `#message-log` with content, author, channel,
  send + delete timestamps, whether it was a reply (and to whom), and — via the
  audit log — **who deleted it** (the author themselves or a moderator). Needs
  **View Audit Log**.
- **Anti-spam / anti-scam** ([`cogs/antispam_cog.py`](cogs/antispam_cog.py)) —
  auto-removes message floods, repeated messages, mass-mentions, and Discord
  invite / scam links, and briefly times out the offender. All thresholds are
  configurable; mods (Manage Messages) are exempt. Needs **Manage Messages** +
  **Moderate Members**.
- **File / image safety scan** ([`cogs/filescan_cog.py`](cogs/filescan_cog.py)) —
  on every upload: removes **dangerous file types** (exe/scr/jar/apk/…), checks
  files against **VirusTotal** by hash if `VIRUSTOTAL_API_KEY` is set (hash only —
  the file is never uploaded), and classifies **images/GIFs for NSFW** via Gemini
  vision (removed if explicit; skipped in age-gated NSFW channels). *Discord has
  no pre-send hook, so this removes within ~1-2s of posting, not before.*
- **Anti-manipulation tactic callouts** ([`cogs/antimanip_cog.py`](cogs/antimanip_cog.py)) —
  flags known social-engineering **tactics** (phishing, fake account-verification,
  giveaway bait, money-doubler, staff impersonation), removes the message, posts a
  short public **safety notice about the tactic**, and alerts mods in
  `#mod-alerts`. It targets the scam *behaviour*, never labels a person's
  character; real staff (Manage Messages) are exempt.
- **Anti-cyberbullying** ([`cogs/antiharass_cog.py`](cogs/antiharass_cog.py)) —
  detects targeted insults and self-harm encouragement, deletes the message, and
  **@mentions the author with one warning**. If they do it again while the
  warning is active, they're **muted for 30 minutes** (`HARASS_MUTE_SECONDS`).
  Mods exempt. Needs **Manage Messages** + **Moderate Members**.

### Profanity filter

Curse words are auto-censored by [`cogs/profanity_cog.py`](cogs/profanity_cog.py).
When a message hits `PROFANITY_THRESHOLD` profane words, the bot deletes it and —
with `PROFANITY_ACTION=censor` — reposts a starred version
(`🔇 **Name:** what the f*** s***`). Set `PROFANITY_ACTION=delete` to just remove
it with a brief warning. Members with **Manage Messages** are exempt by default,
and you can extend the word list via `PROFANITY_EXTRA_WORDS`. Needs the bot to
have **Manage Messages**.

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

## Invite the bot to your server

1. **Get your Application ID** — [Developer Portal](https://discord.com/developers/applications)
   → your app → **General Information** → copy the **Application ID**.
2. **Enable intents** — **Bot** tab → **Privileged Gateway Intents** → turn on
   **Server Members Intent** and **Message Content Intent** (required).
3. **Open the invite link** (replace `YOUR_APP_ID`):

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=1099511753875&scope=bot+applications.commands
   ```

   `permissions=1099511753875` grants exactly what zafven needs:

   | Permission | Used for |
   |---|---|
   | View Channels · Send Messages · Embed Links · Attach Files | posting readings & audit files |
   | Read Message History | `/vibe`, `/profile`, `/kick_inactive` scan |
   | Manage Messages | profanity filter + anti-spam (delete) |
   | Moderate Members | anti-spam timeouts |
   | View Audit Log | attributing deleted messages (self vs mod) |
   | Kick Members | `/kick_inactive` |
   | Manage Channels | auto-creating welcome / log channels |
   | Create Instant Invite | the reinvite DM |

   *(Or use **OAuth2 → URL Generator**: tick `bot` + `applications.commands`, then
   those permissions, and copy the generated URL.)*
4. **Authorize** — open the link, pick your server (you need **Manage Server**
   there), and confirm. The bot now appears in your member list.
5. **It must be running to respond** — the bot shows **offline** until the Railway
   deploy is live with `DISCORD_TOKEN` + `GEMINI_API_KEY` set. Once the logs say
   `zafven online as …`, type `/` in any channel to see its commands.

> Slash commands can take up to ~1 hour to appear globally. To make them show
> **instantly** while testing, set `GUILD_ID` to your server's ID (enable Discord
> Developer Mode → right-click the server → **Copy Server ID**).

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | — | **Required.** Bot token |
| `GEMINI_API_KEY` | — | **Required.** Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | multimodal model for readings + vision |
| `GEMINI_WEB_SEARCH` | `auto` | `auto` / `on` / `off` for `/predict` grounding |
| `PROFANITY_FILTER_ENABLED` | `true` | toggle the curse-word filter |
| `PROFANITY_ACTION` | `censor` | `censor` (repost starred) or `delete` |
| `PROFANITY_THRESHOLD` | `1` | curse words per message before acting |
| `PROFANITY_EXTRA_WORDS` | *(blank)* | extra words to censor |
| `PROFANITY_BYPASS_MODS` | `true` | exempt members with Manage Messages |
| `ANTISPAM_ENABLED` | `true` | toggle anti-spam/scam |
| `ANTISPAM_MAX_MENTIONS` | `5` | mentions per message before acting |
| `ANTISPAM_TIMEOUT_SECONDS` | `300` | how long to mute a spammer (0 = no mute) |
| `WELCOME_CHANNEL` | `welcome` | channel for the join welcome card |
| `DELETED_LOG_CHANNEL` | `message-log` | channel for the deleted-message log |
| `DATA_CHANNEL` | `zafven-data` | hidden channel used for persistence (XP, capsules, ciphers) |
| `RANKS_ENABLED` | `true` | toggle initiation XP/ranks |
| `RANK_LADDER` | `Seeker:1,Initiate:3,…` | `Role:level` ladder for auto-roles |
| `DAILY_ENABLED` / `DAILY_CHANNEL` / `DAILY_HOUR_UTC` | `true` / `oracle` / `13` | daily broadcast schedule |
| `PROFILE_OPTOUT_ROLES` | `no-readings` | roles that can't be `/profile`d |
| `GUILD_ID` | *(blank)* | restrict commands to one guild for instant sync |
| `MEMBER_LOG_CHANNEL` | `member-log` | join/leave log channel |
| `PROTECTED_ROLES` | `Admin,Moderator,Mod,Booster` | never auto-kicked |
| `DEFAULT_INACTIVE_DAYS` | `30` | inactivity threshold |
| `ACTIVITY_SCAN_LIMIT` | `2000` | messages scanned per channel |
| `JOIN_GRACE_DAYS` | `7` | new-member exemption |

## Mod alerts

Anti-manipulation flags, file-scan removals, and member `/report`s all post to a
hidden, mod-visible `#mod-alerts` channel and **@mention the mod roles**
(`MOD_ROLES`, default `Moderator,Admin,Mod`). `/report` keeps a human in the loop:
the bot forwards the reported message + reason, it never renders a verdict. (To
ping a non-mentionable mod role, the bot's role may need *Mention @everyone, @here,
and All Roles*.)

## Persistence (no database)

State that must survive restarts — XP, time capsules, active ciphers — is stored
in Discord itself via [`core/store.py`](core/store.py): a hidden `zafven-data`
channel holds one marker message per namespace with the JSON as a file
attachment, loaded into memory on first use. Railway's disk is ephemeral, so this
keeps the "storage lives in Discord" design end-to-end.

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
