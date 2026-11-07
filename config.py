"""Central configuration for zafven, loaded from environment / .env."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Discord ──────────────────────────────────────────────────────────────
TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()
VOICE_BOT_TOKENS: list[str] = _csv("VOICE_BOT_TOKENS", "")
GUILD_ID: int | None = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID", "").strip() else None
PUBLIC_BOT_MODE: bool = os.getenv("PUBLIC_BOT_MODE", "true").strip().lower() in {"1", "true", "yes"}
HOUSEOFASHER_INVITE_URL: str = "https://discord.gg/M9hnebRwvk"
HOUSEOFASHER_GUILD_ID: int = _int("HOUSEOFASHER_GUILD_ID", 0)
ASHER_USER_ID: int = _int("ASHER_USER_ID", 909200076637872188)
ASHER_MAX_SAMPLES: int = _int("ASHER_MAX_SAMPLES", 200)
ASHER_SCAN_PER_CHANNEL: int = _int("ASHER_SCAN_PER_CHANNEL", 500)
MEMBER_LOG_CHANNEL: str = os.getenv("MEMBER_LOG_CHANNEL", "member-log").strip()
WELCOME_CHANNEL: str = os.getenv("WELCOME_CHANNEL", "welcome").strip()
DELETED_LOG_CHANNEL: str = os.getenv("DELETED_LOG_CHANNEL", "message-log").strip()
MESSAGE_LOG_ENABLED: bool = os.getenv("MESSAGE_LOG_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
PROTECTED_ROLES: list[str] = [r.lower() for r in _csv("PROTECTED_ROLES", "Admin,Moderator,Mod,Booster")]
DEFAULT_INACTIVE_DAYS: int = _int("DEFAULT_INACTIVE_DAYS", 30)
ACTIVITY_SCAN_LIMIT: int = _int("ACTIVITY_SCAN_LIMIT", 2000)
JOIN_GRACE_DAYS: int = _int("JOIN_GRACE_DAYS", 7)

# ── Gemini LLM (required) ────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL: str = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
# Gemini models are multimodal, so one model handles both text and vision.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
# Live chat uses its own (optionally faster) model so banter stays snappy while
# readings/research can use a heavier model. Defaults to the main model.
CHAT_MODEL: str = os.getenv("CHAT_MODEL", "").strip() or GEMINI_MODEL
GEMINI_MAX_TOKENS: int = _int("GEMINI_MAX_TOKENS", 1200)
GEMINI_TIMEOUT: int = _int("GEMINI_TIMEOUT", 45)
# 2.5 models "think" before answering, which can eat the output budget and cut
# replies off mid-sentence. 0 disables thinking; -1 = dynamic; >0 = fixed budget.
GEMINI_THINKING_BUDGET: int = _int("GEMINI_THINKING_BUDGET", 0)
GEMINI_WEB_SEARCH: str = os.getenv("GEMINI_WEB_SEARCH", "auto").strip().lower()
# How aggressively Gemini's own filter blocks output. BLOCK_NONE = loosest Gemini
# allows. "OFF"/"NONE" -> BLOCK_NONE.
_safety = os.getenv("GEMINI_SAFETY", "BLOCK_NONE").strip().upper()
GEMINI_SAFETY: str = "BLOCK_NONE" if _safety in {"OFF", "NONE", ""} else _safety
# Add the direct-answer style preference (legacy environment-variable name).
UNCENSORED_MODE: bool = os.getenv("UNCENSORED_MODE", "true").strip().lower() in {"1", "true", "yes"}

# ── Chat-triggered member readings ──────────────────────────────────────
# Members with any of these roles are exempt and cannot be profiled.
PROFILE_OPTOUT_ROLES: list[str] = [r.lower() for r in _csv("PROFILE_OPTOUT_ROLES", "no-readings")]

# ── Manual member reports ────────────────────────────────────────────────
MOD_ALERT_CHANNEL: str = os.getenv("MOD_ALERT_CHANNEL", "mod-alerts").strip()
MOD_ROLES: list[str] = _csv("MOD_ROLES", "Moderator,Admin,Mod")

# ── Music player (YouTube → voice channel) ───────────────────────────────
MUSIC_ENABLED: bool = os.getenv("MUSIC_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
# Max tracks a single guild can have queued at once.
MUSIC_MAX_QUEUE: int = _int("MUSIC_MAX_QUEUE", 100)
# Optional path to a cookies.txt export — lets yt-dlp past YouTube's "sign in to
# confirm you're not a bot" checks that hit datacenter IPs (e.g. on Railway).
MUSIC_COOKIE_FILE: str = os.getenv("MUSIC_COOKIE_FILE", "").strip()
# Easier on hosts with no filesystem: paste the whole cookies.txt CONTENT here and
# it's written to a temp file at runtime. MUSIC_COOKIE_FILE takes precedence.
MUSIC_COOKIES: str = os.getenv("MUSIC_COOKIES", "")
# Optional proxy URL (e.g. http://user:pass@host:port) for yt-dlp — routing
# through a residential proxy also gets past YouTube's datacenter bot check.
MUSIC_PROXY: str = os.getenv("MUSIC_PROXY", "").strip()
# Fall back to SoundCloud for searches and YouTube links with a retrievable title.
MUSIC_SOUNDCLOUD_FALLBACK: bool = os.getenv("MUSIC_SOUNDCLOUD_FALLBACK", "true").strip().lower() in {"1", "true", "yes"}
# Allow the persistent 24/7 mode (/247) that keeps the bot in the VC and rejoins
# after a restart or disconnect. Set false to forbid it.
MUSIC_247_ALLOWED: bool = os.getenv("MUSIC_247_ALLOWED", "true").strip().lower() in {"1", "true", "yes"}
# FFmpeg audio filter chain for Discord output. The default resamples cleanly to
# Discord's 48 kHz stereo target and limits peaks that can buzz on phone speakers.
MUSIC_AUDIO_FILTER: str = os.getenv(
    "MUSIC_AUDIO_FILTER",
    "aresample=48000:resampler=soxr:precision=28,alimiter=limit=0.95"
).strip()
# Low-frequency tremolo — a gentle amplitude pulse on the music signal (NOT a
# change to the listener's device). Default 4 Hz for the signature "vibe". The
# harshness is set by the DEPTH, not the rate: 0.25 buzzes, ~0.08 is a subtle
# breathing pulse. 0 Hz turns the effect off entirely.
MUSIC_TREMOLO_HZ: int = _int("MUSIC_TREMOLO_HZ", 4)
try:
    MUSIC_TREMOLO_DEPTH: float = float(os.getenv("MUSIC_TREMOLO_DEPTH", "0.08") or 0.08)
except ValueError:
    MUSIC_TREMOLO_DEPTH = 0.08

# Bible reference replies
BIBLE_REPLY_ENABLED: bool = os.getenv("BIBLE_REPLY_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
BIBLE_TRANSLATIONS: list[str] = _csv("BIBLE_TRANSLATIONS", "kjv,web,asv,dra")
BIBLE_MAX_TRANSLATIONS: int = _int("BIBLE_MAX_TRANSLATIONS", 4)
BIBLE_MAX_REFERENCES: int = _int("BIBLE_MAX_REFERENCES", 2)
BIBLE_TIMEOUT_SECONDS: int = _int("BIBLE_TIMEOUT_SECONDS", 8)


# ── Culture adaptation (learn the server's vibe) ─────────────────────────
CULTURE_ADAPT_ENABLED: bool = os.getenv("CULTURE_ADAPT_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
CULTURE_REFRESH_HOURS: int = _int("CULTURE_REFRESH_HOURS", 12)

# ── Live chat personality (Zafven) ───────────────────────────────────────
CHAT_ENABLED: bool = os.getenv("CHAT_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
# Chance (0.0-1.0) she chimes in on a message that didn't address her. 0 = only
# replies when @mentioned or replied to.
CHAT_AMBIENT_CHANCE: float = float(os.getenv("CHAT_AMBIENT_CHANCE", "0.0") or 0.0)
CHAT_COOLDOWN_SECONDS: int = _int("CHAT_COOLDOWN_SECONDS", 6)
CHAT_CONTEXT_MESSAGES: int = _int("CHAT_CONTEXT_MESSAGES", 12)
# Restrict chatting to these channel names (comma-separated). Empty = everywhere.
CHAT_CHANNELS: list[str] = _csv("CHAT_CHANNELS", "")
# Addressed chat can scan other readable channels for short source snippets and
# quote who said them when answering questions about server context.
CHAT_CROSS_CHANNEL_SOURCES: bool = os.getenv("CHAT_CROSS_CHANNEL_SOURCES", "true").strip().lower() in {"1", "true", "yes"}
CHAT_SOURCE_CHANNELS: int = _int("CHAT_SOURCE_CHANNELS", 8)
CHAT_SOURCE_MESSAGES_PER_CHANNEL: int = _int("CHAT_SOURCE_MESSAGES_PER_CHANNEL", 30)
CHAT_SOURCE_SNIPPETS: int = _int("CHAT_SOURCE_SNIPPETS", 6)

# ── Voice (Gemini text-to-speech) ────────────────────────────────────────
GEMINI_TTS_MODEL: str = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()
# Prebuilt Gemini voice (Kore, Puck, Aoede, Leda, Zephyr, Charon, Fenrir, …).
GEMINI_TTS_VOICE: str = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()

# ── YouTube + knowledge reports ──────────────────────────────────────────
# Optional YouTube Data API v3 key for /youtube search (real video links).
YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "").strip()
# Public channel where /learn posts knowledge / intelligence reports.
KNOWLEDGE_CHANNEL: str = os.getenv("KNOWLEDGE_CHANNEL", "knowledge").strip()

# ── Phase 2: persistence + scheduled/stateful features ───────────────────
DATA_CHANNEL: str = os.getenv("DATA_CHANNEL", "zafven-data").strip()
BOT_DATA_DIR: str = os.getenv("BOT_DATA_DIR", "./zafven-storage").strip()
MESSAGE_BACKUP_ENABLED: bool = os.getenv("MESSAGE_BACKUP_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
MESSAGE_BACKUP_CATEGORY: str = os.getenv("MESSAGE_BACKUP_CATEGORY", "message-backups").strip()
USER_MEMORY_CATEGORY: str = os.getenv("USER_MEMORY_CATEGORY", "zafven-memory").strip()

# Initiation ranks (activity XP -> roles)
RANKS_ENABLED: bool = os.getenv("RANKS_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
RANK_COOLDOWN_SECONDS: int = _int("RANK_COOLDOWN_SECONDS", 60)
# Role ladder as "RoleName:level" pairs; level = floor(sqrt(xp/100)).
RANK_LADDER: list[str] = _csv("RANK_LADDER", "Helper:1,Regular:3,Trusted:6,Steward:10,Elder:15")

# ── Welcome DMs + invite tracking / referral leaderboard ─────────────────
INVITES_ENABLED: bool = os.getenv("INVITES_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
WELCOME_DM_ENABLED: bool = os.getenv("WELCOME_DM_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
# Optional invitation override; blank uses the supplied Houseofasher relaunch text.
# Supports {invite_link}, otherwise the link is appended.
WELCOME_DM_MESSAGE: str = os.getenv("WELCOME_DM_MESSAGE", "").strip()
# Channel where "X invited Y" join credits are posted. Blank = don't announce.
INVITE_LOG_CHANNEL: str = os.getenv("INVITE_LOG_CHANNEL", "invite-log").strip()


def validate() -> list[str]:
    """Return a list of fatal config problems (empty == OK)."""
    problems = []
    if not TOKEN:
        problems.append("DISCORD_TOKEN is not set.")
    if len(set([TOKEN, *VOICE_BOT_TOKENS])) != len([TOKEN, *VOICE_BOT_TOKENS]):
        problems.append("Use distinct bot accounts/tokens for VOICE_BOT_TOKENS; do not repeat DISCORD_TOKEN.")
    if not GEMINI_API_KEY:
        problems.append("GEMINI_API_KEY is not set (Gemini is required for readings).")
    if GEMINI_WEB_SEARCH not in {"auto", "on", "off"}:
        problems.append("GEMINI_WEB_SEARCH must be one of: auto, on, off.")
    return problems
