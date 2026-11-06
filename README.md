# zafven

Zafven is a Discord companion with music, research, coding, Bible references,
community features, and manual server-management tools.

The current startup set intentionally does not load the old occult/esoteric reading
commands. Bible references are handled as data lookups, music is handled through
Discord voice, and server state is persisted in the hidden `zafven-data` channel.

## Public bot installation and Houseofasher

Public distribution is now the default (`PUBLIC_BOT_MODE=true`). This source update
does not change settings in Discord's Developer Portal or deploy the bot. To make
the actual application publicly installable:

1. In the application's Discord Developer Portal settings, enable **Public Bot**.
2. Enable server/Guild Install and the `bot` and `applications.commands` scopes.
3. Keep `GUILD_ID` blank so commands register globally; configure the required
   token, Gemini key, intents, persistent storage, and deployment as described below.
4. Once running, `/invitebot` produces the application's public authorization URL.
   The installing user still needs permission to add applications to the target server.
5. `/publicstatus` reads Discord's current Public Bot flag and command-sync mode.

The default invite requests normal chat/voice permissions, not Administrator or
Manage Roles. Each server grants optional administrative capabilities separately.
Zafven **cannot be made unremovable**: the server retains control of its bot
membership, permissions, and roles. There is no removal bypass, hidden rejoin,
automatic permission escalation, or ownership transfer implementation.

### Promotion

The promotion destination is fixed to <https://discord.gg/M9hnebRwvk>.
Its metadata could not be verified in the development environment (HTTP 403),
so the source does not claim the invite is currently active.

- `/houseofasher` shows the invite privately to the requester.
- `/houseofasher private:True` sends one personalized DM naming the requester,
  using the supplied invitation copy and the Houseofasher link. A failed DM returns
  the link in the private command response. This does not subscribe the user.
- `/houseofasher_updates enabled:True|False` opts in/out of future invitation DMs.
- A server manager uses `/promotion_setup channel:<channel>` to approve a destination.
  Calling it without a channel disables server posts. No promotional posts occur
  automatically on installation.
- `/promote_houseofasher` lets a server manager post a join button in that approved
  channel, without mass mentions. No recurring campaign is scheduled automatically.

Public-mode join events do not send automatic promotional welcome DMs. Public-mode
batch campaigns (`/reinvite` and its `/announcewelcome` alias) run only in the server
configured by `HOUSEOFASHER_GUILD_ID`, target only subscribed known/current users,
and recheck consent at delivery time. Pending entries without current consent are
skipped. Set the actual Houseofasher server ID before using those batches; it could
not be discovered from the invite in this environment. The bot never forces a user
to join or unbans them. Inactivity-cleanup DMs are operational notices rather than
unsolicited promotional messages in public mode.

The original private-server behavior described later is available only with
`PUBLIC_BOT_MODE=false`; public-mode consent requirements take precedence.

### Bot-owner role delegation

The application owner is identified using discord.py's owner check (including its
supported application-team ownership behavior), not a caller-supplied owner ID.

1. A local server member with Manage Roles approves a specific role using
   `/owner_role_access role:<role> enabled:True`. The approving member must be the
   server owner or be above that role in the role hierarchy.
2. The bot's application owner uses `/owner_role member:<member> role:<role>
   grant:True|False` to add/remove an approved role in that server.
3. The server can revoke approval with `enabled:False`, revoke Manage Roles, move
   the bot lower, deny command access, or remove the bot.

No roles are approved by default. Discord must grant the bot Manage Roles and place
its highest role above the assigned role. Managed/integration roles, `@everyone`,
unapproved roles, nonowner callers, and cross-server targets are rejected.

`/privacy` explains message archives, personal memory, Gemini context, and DM controls.
The one-time server onboarding message also discloses the default-off promotion and
role delegation. Message backup/memory settings and permissions still need to match
the installing server's expectations; source code is not a hosted privacy policy.

References: [Discord installation/OAuth](https://github.com/discord/discord-api-docs/blob/main/developers/topics/oauth2.mdx),
[permissions and roles](https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx),
[Developer Policy](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy).

## What It Does

### Chat

- Mention Zafven or reply to one of her messages to chat.
- She can remember user-provided notes with `/memory` and `/forget`.
- Admins can tune tone with `/persona` and add server-specific knowledge with `/brain`.
- When answering questions that may depend on prior server discussion, Zafven scans a
  small number of readable channels and passes attributed snippets into the prompt.
  If she uses those snippets, she is instructed to quote the channel and sender.

### Zafven v74.4 personality, adaptation, and personal memory

The personality core is derived from the supplied portable v74.4 ZIP's system
prompt and skill instructions. Imported identity labels are renamed to Zafven.
`brains/zafven_v74_4.md` is loaded with the persona/companion instructions used by
chat, Q&A, and task commands. `docs/personality-source.json` records source hashes
and the selected entries. The ZIP's installer, provider adapters, and separate CLI
runtime were not installed or executed; this is not a claim that the absent full
reference library or autonomous tools were imported. Your previously supplied
invitation text and its personal references are preserved unchanged.

Zafven adapts response style from this user's expressed preferences and corrections,
using bounded retrieved context rather than changing model weights. She can use
playful trolling, dry comebacks, and teasing when appropriate. This is banter rather
than sustained targeting, private-information exposure, or invented accusations.
The behavior remains model-generated, so exact tone is not guaranteed by tests.

Personal memory is isolated by **server ID and user ID**, with separate areas for
notes, facts, projects, feedback, preferences, and recent exchanges. New memory is
saved to the existing local SQLite database and mirrored every five seconds to a
hidden `memory-<user ID>` channel under `zafven-memory` (or `USER_MEMORY_CATEGORY`).
Only the bot and server administrators can access those channels. Users inspect and
manage their own memory through ephemeral commands, not direct channel access.
Hidden does not mean inaccessible to administrators or encrypted at rest.

- `/adapt style:brief banter:troll` sets your reply preferences. Banter choices are
  `off`, `light` (default), or `troll`. `/adapt` with no values displays preferences.
- Saying “stop trolling”, “stop teasing”, or “don't roast me” in addressed chat
  saves banter `off`. Use `/adapt` to choose another setting later.
- `/remember area:projects text:...` saves a note. Areas: `notes`, `facts`, `projects`,
  and `feedback`. Each holds the latest 20 entries, up to 1,000 characters each.
- `/memory` privately downloads your active state and preferences as JSON.
- `/forget` resets your active memory/preferences and conversational mood; the
  mirrored snapshot updates afterward. General message backups and Discord history
  remain separate. Legacy shared-channel personal notes are removed on reset.

Direct chat and `/ask` retrieve personal context and keep up to 20 recent exchanges
(1,000 characters per side). Recent exchanges are reused only in their original
channel. Durable facts/projects are available to the same user across channels;
the prompt directs Zafven not to expose private conversation in public. Automatic
memory/preference extraction relies on the model honoring its instructions; users
can inspect/reset it. Saved preferences are data, not permission to execute tools
or edit another user's memory.

Older shared-channel notes migrate on first access. If local state is missing, the
bot can recover a matching bot-authored personal snapshot from its memory channel.
It checks the server/user IDs. A still-unsynced local change cannot be recovered
from an older snapshot, so persistent storage is still required. Local state remains
usable if channel creation/upload fails. The snapshot is replaced, not appended,
and pending newer revisions are retained during concurrent writes. Existing public
destinations are hardened before being used, and categories rotate when full.
Discord's total channel/storage limits still apply.

Personal memory channels are excluded from message backups, history backfill,
cross-channel chat sources, culture/mood sampling, and member-message sampling.
They are created on demand for users who interact or save preferences/notes.

### Message backups and former-member reinvites

Message backups are enabled by default. New guild messages the bot receives are
stored as full text plus author/channel IDs, timestamps, reply references, embed
data, sticker metadata, and attachment names/URLs in `community.sqlite3` under
`BOT_DATA_DIR`. Raw edit/delete/bulk-delete events are also recorded. DMs are not
archived. The data, mod-alert, deleted-log, and backup channels are excluded to
avoid copying private internal state or creating archive loops.

A worker mirrors records as JSONL attachments into administrator-only daily
`messages-YYYY-MM-DD` channels under `message-backups`. Additional private categories
are created when the category fills. The date is the mirror's UTC date. It hardens
existing destination channel overwrites before reuse. Original text is not shortened
and mentions in archived content do not ping anyone. Attachment URLs are metadata,
**not permanent copies of uploaded files**; source media links can expire.

Local records remain if Discord channel creation or upload fails, and mirroring
retries. A crash after upload but before marking completion can create a duplicate
channel batch. Channel/server capacity and storage capacity still apply. This is
an archive on the same Discord server plus local storage, not an independent
off-site disaster-recovery service.

**Railway:** mount a persistent volume and point `BOT_DATA_DIR` to its mount path
(for example `/data/zafven`). Without a persistent volume, local archive/recipient/
queue state is lost when the host replaces the filesystem. Already-mirrored Discord
files remain, but the bot does not rebuild its local queue/index from them.

Administrator commands (Manage Server):

1. `/backup_history limit:0` scans all available readable text-channel, active-thread,
   and public archived-thread history, and records historical human authors in the
   known-member directory. Positive limits restrict each channel/thread. It runs
   in the background. Inaccessible/private archived threads are not enumerated.
2. `/backup_status` shows stored records, pending channel copies, and scan status.
   Rerunning a completed/interrupted history scan deduplicates identical snapshots.
3. `/discover_members` adds current members, targets in available kick audit logs,
   and departed-member IDs from this bot's existing `member-log` embed footers.
4. `/reinvite audience:all` previews the directory without sending DMs or creating
   an invite. Wait until history/discovery scans have finished before queuing.
5. `/reinvite audience:all dry_run:False` creates a never-expiring server invite
   and queues the supplied Houseofasher invitation for current and known former
   users. `audience:former` excludes current members; `current` does the reverse.
6. `/announcewelcome` is an alias that queues the same `all` campaign immediately.
7. `/reinvite_status` shows pending, sending, sent, failed, skipped, and cancelled
   counts. `/reinvite_cancel` cancels pending entries; an in-flight DM can complete.

The batch worker attempts one recipient every two seconds and uses discord.py's
normal rate-limit handling. Bot accounts are skipped. Successful/failed/cancelled
recipients are not added again under the same campaign name. An interrupted send
stays `sending` (uncertain) rather than being automatically retried and duplicated.
Use a new campaign name only when intentionally sending a new round. Queued pending
deliveries resume when the bot restarts. Keep one bot process per database.

The exact supplied invitation is shared by welcome DMs, inactivity-removal DMs,
and the batch campaign. `WELCOME_DM_MESSAGE` overrides the default; use
`{invite_link}` to place the link, otherwise it is appended. Previously configured
deployment text must be cleared/updated to use the new default.

This does not unban anyone or bypass closed DMs. Banned accounts are excluded from
candidate lists when the bot has permission to list bans. Without that permission,
their ban status may be unknown and the link cannot grant access past a ban.
Discord does not expose a complete lifetime former-member list. Members absent
from all readable records cannot be recovered, and already-deleted historical
messages cannot be reconstructed. Message Content and Members intents and relevant
history/audit/channel/invite permissions are required.

API references: [member/event access](https://discordpy.readthedocs.io/en/stable/api.html),
[Discord guild member APIs](https://github.com/discord/discord-api-docs/blob/main/developers/resources/guild.mdx).

### Research, coding, and community

- `/ask`, `/research`, `/synthesize`, and `/council` answer questions and compare ideas.
- `/youtube` finds videos; `/learn` posts topic or transcript reports to `#knowledge`.
- `/tldr` summarizes channel discussion; `/askdoc` answers PDF/text questions.
- `/imagine` analyzes an uploaded image; `/grab` reposts linked media.
- `/audit` returns code findings and proposed fixes in one attachment.
- `/forge` returns a design and generated code immediately, without approval buttons.
  Neither coding command executes, applies, tests, or deploys the generated code.
- `/vc join`, `/vc speak`, `/say`, and `/vc leave` provide text-to-speech.
  Microphone listening is not implemented.
- `/teach`, `/taught`, `/unlearn`, `/culture`, and `/brain` manage server context.
- `/vibe`, `/feelings`, `/mood`, `/rank`, `/leaderboard`, `/capsule`, `/cipher`,
  and `/solve` retain the community features.
- Mention Zafven and one other member with a profile/analysis request to use the
  existing member-reading feature. The `no-readings` opt-out role is respected.
  The unused standalone `/profile` cog has been removed.

### Bible References

When someone posts a Bible reference like `John 3:16` or `1 Cor 13:4-7`, Zafven
replies to that Discord message with exact passage text from configured translations.

By default this uses public-domain/open translations from [bible-api.com](https://bible-api.com/):

- `kjv`
- `web`
- `asv`
- `dra`

Tune this with:

```env
BIBLE_REPLY_ENABLED=true
BIBLE_TRANSLATIONS=kjv,web,asv,dra
BIBLE_MAX_TRANSLATIONS=4
BIBLE_MAX_REFERENCES=2
BIBLE_TIMEOUT_SECONDS=8
```

### Music

Core commands:

- `/play <link or search>`
- `/playnext <link or search>`
- `/restartmusic`
- `/loop track|queue|off`
- `/queue`
- `/shuffle`
- `/remove <position>`
- `/clear`
- `/nowplaying`
- `/skip`
- `/pause`
- `/resume`
- `/volume <0-200>`
- `/stop`
- `/247 <on|off>`

Shared server default music (available to all members):

- `/defaultmusic add <query>`
- `/defaultmusic list`
- `/defaultmusic remove <position>`
- `/defaultmusic clear`
- `/defaultmusic start`

Personal playlists:

- `/playlist add <query>`
- `/playlist list`
- `/playlist remove <position>`
- `/playlist clear`
- `/playlist start`
- `/playlist share <member>`
- `/playlist accept`
- `/playlist reject`

`/playlist start` uses the caller's personal playlist when nonempty, otherwise the
server default playlist. Music controls and shared-default editing have no DJ or
server-owner gate. Discord's own application-command permissions still apply.

Discord allows one voice connection per bot account per server. Zafven can be in
voice in multiple servers at the same time, but one bot account cannot sit in two
voice channels inside the same server simultaneously.

Mobile audio compatibility is improved by forcing a clean 48 kHz stereo output and
limiting peaks before Discord encodes the audio:

```env
MUSIC_AUDIO_FILTER=aresample=48000:resampler=soxr:precision=28,alimiter=limit=0.95
MUSIC_TREMOLO_HZ=4
```

`MUSIC_TREMOLO_HZ` defaults to `4` and can be set to `4` through `8` with
`/musicfreq`, or `0` to disable.
This applies an FFmpeg tremolo effect to future tracks; it does not change listener
hardware or operating-system device sample rates.

### Manual moderation and server tools

- Welcome/member log channels
- Deleted-message log channel
- Inactive-member cleanup
- User reports to mod alerts
- Welcome DMs, personal invite links, referral counts, and `/announcewelcome`

No automatic message policing remains: profanity/slur/sexual-word deletion,
language strikes/timeouts, spam/invite/scam filtering, harassment/manipulation
filters, file/NSFW scanning, and seven-sins correction DMs have been removed.
Moderators can still handle reports manually. Referral totals are cumulative;
the bot does not reset monthly counts or award Nitro.

### Cleanup and remaining boundaries

The cleanup removes the unused standalone profile command, unused daily-broadcast
and microphone-listening settings, and obsolete moderation helpers/configuration.
Personality prompts no longer force lowercase-only output, religious correction,
a fixed comedy routine, or pretending to be human. Code generation has no second
approval step. The old `UNCENSORED_MODE` variable is retained for compatibility as
an optional direct-answer style preference; it does not override provider rules.

Existing deployments can remove `ANTISPAM_*`, `ANTIMANIP_*`, `HARASS_*`,
`PROFANITY_*`, `FILESCAN_*`, `NSFW_*`, `BLOCKED_EXTENSIONS`, `VIRUSTOTAL_API_KEY`,
`SEVEN_SINS_*`, `MUSIC_DJ_ROLE`, `DAILY_*`, `VOICE_SILENCE_MS`, `VOICE_MIN_MS`,
`VOICE_REPLY_TOKENS`, and `VOICE_MODEL`. They are no longer read. Stored legacy
strike data is left untouched, so this source cleanup does not delete server data.

Upload/input caps, API timeouts, cooldowns, Discord permission checks for destructive
or administrative actions, profile opt-outs, and media URL validation remain.
Image-analysis privacy instructions also remain. These are resource, access, and
privacy boundaries rather than automatic content moderation. Existing cross-channel
sampling follows the bot's visibility: configure its channel access appropriately.

Deleted-message logs need an explicitly restricted channel if logs should be private;
the log cog does not set moderator-only overwrites automatically. The data and
mod-alert channels are created with their own visibility overwrites when absent.

Offline verification (no Discord login or live Gemini request):

```bash
python -m compileall -q bot.py config.py cogs core scripts
python scripts/smoke_test.py
python scripts/community_test.py
python scripts/personality_memory_test.py
python scripts/public_bot_test.py
```

## Setup

1. Create a Discord application and bot token.
2. Invite the bot with slash-command and voice permissions.
3. Copy `.env.example` to `.env`, or set the same variables on Railway.
4. Set required variables:

```env
DISCORD_TOKEN=your-discord-bot-token
GEMINI_API_KEY=your-gemini-api-key
```

5. Install dependencies and run:

```bash
pip install -r requirements.txt
python bot.py
```

On Railway, the included `Procfile`, `nixpacks.toml`, and `railway.json` are ready for
deployment. YouTube playback on hosted datacenter IPs may require `MUSIC_COOKIE_FILE`
or `MUSIC_COOKIES`.

## Important Permissions

- Message Content Intent: required for Bible reference detection and chat replies.
- Read Message History: required for summaries and cross-channel source quoting.
- Connect/Speak: required for voice and music.
- Manage Channels: optional, used to create persistence/log channels.
- Kick Members: required for manual inactive-member cleanup, which retains confirmation.
- Manage Messages: required for cipher creation and removing learned facts.
- Manage Server: required for persona/brain management and bulk welcome DMs.
- Manage Roles: required for XP rank roles.
- View Audit Log: used to estimate who deleted a message.
