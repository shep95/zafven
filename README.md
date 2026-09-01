# zafven

Zafven is a Discord companion, music, Bible-reference, knowledge, and moderation bot.

The current startup set intentionally does not load the old occult/esoteric reading
commands. Bible references are handled as data lookups, music is handled through
Discord voice, and server state is persisted in the hidden `zafven-data` channel.

## What It Does

### Chat

- Mention Zafven or reply to one of her messages to chat.
- She can remember user-provided notes with `/memory` and `/forget`.
- Admins can tune tone with `/persona` and add server-specific knowledge with `/brain`.
- When answering questions that may depend on prior server discussion, Zafven scans a
  small number of readable channels and passes attributed snippets into the prompt.
  If she uses those snippets, she is instructed to quote the channel and sender.

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

Server-creator default music:

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

If a user starts their playlist and has not made one yet, Zafven falls back to the
server default playlist. Once the user creates their own playlist, `/playlist start`
uses only that user's playlist.

Discord allows one voice connection per bot account per server. Zafven can be in
voice in multiple servers at the same time, but one bot account cannot sit in two
voice channels inside the same server simultaneously.

Mobile audio compatibility is improved by forcing a clean 48 kHz stereo output and
limiting peaks before Discord encodes the audio:

```env
MUSIC_AUDIO_FILTER=aresample=48000:resampler=soxr:precision=28,alimiter=limit=0.95
MUSIC_TREMOLO_HZ=4
```

`MUSIC_TREMOLO_HZ` defaults to `4` and can be set with `/musicfreq`, or `0` to
disable. Supported stages:

- `delta` - `0.5 Hz` to `4 Hz`. The deepest stage: the floor of measurable
  brainwave activity in a living brain, associated with dreamless deep sleep,
  coma-adjacent states, and rare conscious meditative absorption. This is where
  the body does deep repair work; human growth hormone peaks here and immune
  restoration is most aggressive while the conscious mind is essentially offline.
- `theta` - `4 Hz` to `8 Hz`. The existing low-frequency meditative range.

This applies an FFmpeg tremolo effect to future tracks; it does not change listener
hardware, operating-system device sample rates, or make medical claims.

### Moderation And Server Tools

- Welcome/member log channels
- Deleted-message log channel
- Inactive-member cleanup
- Profanity/slur/sexual-language moderation
- Anti-spam and anti-scam checks
- Optional private seven-deadly-sins nudges
- User reports to mod alerts

Private seven-sins nudges are off by default:

```env
SEVEN_SINS_DM_ENABLED=false
SEVEN_SINS_COOLDOWN_SECONDS=21600
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
- Moderate Members/Manage Messages: required for stronger moderation actions.
