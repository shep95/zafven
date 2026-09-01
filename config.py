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


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Discord ──────────────────────────────────────────────────────────────
TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID: int | None = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID", "").strip() else None
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
# Prepend uncensored truth directive to every LLM system prompt (except explicit opt-outs).
UNCENSORED_MODE: bool = os.getenv("UNCENSORED_MODE", "true").strip().lower() in {"1", "true", "yes"}

# ── /profile (communication-style read of a member) ──────────────────────
# Members with any of these roles are exempt and cannot be profiled.
PROFILE_OPTOUT_ROLES: list[str] = [r.lower() for r in _csv("PROFILE_OPTOUT_ROLES", "no-readings")]

# ── Anti-spam / anti-scam ────────────────────────────────────────────────
ANTISPAM_ENABLED: bool = os.getenv("ANTISPAM_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
# Flood: more than N messages within this many seconds = spam.
ANTISPAM_FLOOD_COUNT: int = _int("ANTISPAM_FLOOD_COUNT", 5)
ANTISPAM_FLOOD_SECONDS: int = _int("ANTISPAM_FLOOD_SECONDS", 7)
# Same message repeated this many times = spam.
ANTISPAM_DUPLICATE_COUNT: int = _int("ANTISPAM_DUPLICATE_COUNT", 3)
# More than this many @mentions in one message = spam.
ANTISPAM_MAX_MENTIONS: int = _int("ANTISPAM_MAX_MENTIONS", 5)
# Delete Discord invite links posted by non-mods.
ANTISPAM_BLOCK_INVITES: bool = os.getenv("ANTISPAM_BLOCK_INVITES", "true").strip().lower() in {"1", "true", "yes"}
# Timeout (mute) duration applied to spammers, in seconds (0 = don't timeout).
ANTISPAM_TIMEOUT_SECONDS: int = _int("ANTISPAM_TIMEOUT_SECONDS", 300)
ANTISPAM_BYPASS_MODS: bool = os.getenv("ANTISPAM_BYPASS_MODS", "true").strip().lower() in {"1", "true", "yes"}

# ── File / image safety scanning ─────────────────────────────────────────
FILESCAN_ENABLED: bool = os.getenv("FILESCAN_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
# NSFW image classification via Gemini vision (costs an API call per image).
NSFW_SCAN_ENABLED: bool = os.getenv("NSFW_SCAN_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
# Don't remove NSFW images in Discord age-gated (NSFW) channels.
NSFW_ALLOW_IN_NSFW_CHANNELS: bool = os.getenv("NSFW_ALLOW_IN_NSFW_CHANNELS", "true").strip().lower() in {"1", "true", "yes"}
# Extra blocked file extensions (added to the built-in list).
BLOCKED_EXTENSIONS: list[str] = _csv("BLOCKED_EXTENSIONS", "")
# Optional VirusTotal API key for known-malware hash lookups.
VIRUSTOTAL_API_KEY: str = os.getenv("VIRUSTOTAL_API_KEY", "").strip()
FILESCAN_MAX_IMAGE_MB: int = _int("FILESCAN_MAX_IMAGE_MB", 8)
FILESCAN_BYPASS_MODS: bool = os.getenv("FILESCAN_BYPASS_MODS", "false").strip().lower() in {"1", "true", "yes"}

# ── Anti-manipulation / anti-scam tactics ────────────────────────────────
ANTIMANIP_ENABLED: bool = os.getenv("ANTIMANIP_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
# Channel where mods get a private alert about flagged messages.
MOD_ALERT_CHANNEL: str = os.getenv("MOD_ALERT_CHANNEL", "mod-alerts").strip()
# Roles pinged when an alert fires (comma-separated role names).
MOD_ROLES: list[str] = _csv("MOD_ROLES", "Moderator,Admin,Mod")
ANTIMANIP_BYPASS_MODS: bool = os.getenv("ANTIMANIP_BYPASS_MODS", "true").strip().lower() in {"1", "true", "yes"}

# ── Anti-cyberbullying ───────────────────────────────────────────────────
HARASS_FILTER_ENABLED: bool = os.getenv("HARASS_FILTER_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
# How long (seconds) to mute a repeat offender. Default 30 minutes.
HARASS_MUTE_SECONDS: int = _int("HARASS_MUTE_SECONDS", 1800)
# How long (seconds) a warning stays "active" before it resets.
HARASS_WARN_WINDOW_SECONDS: int = _int("HARASS_WARN_WINDOW_SECONDS", 3600)
HARASS_BYPASS_MODS: bool = os.getenv("HARASS_BYPASS_MODS", "true").strip().lower() in {"1", "true", "yes"}

# ── Profanity / slur / sexual-language filter ────────────────────────────
# Auto-deletes banned language, warns the member, and mutes on repeat strikes.
PROFANITY_FILTER_ENABLED: bool = os.getenv("PROFANITY_FILTER_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
# How many banned words in one message before the bot acts. 1 = act on any.
PROFANITY_THRESHOLD: int = _int("PROFANITY_THRESHOLD", 1)
# Extra words to treat as profanity (comma-separated), added to the built-in list.
PROFANITY_EXTRA_WORDS: list[str] = _csv("PROFANITY_EXTRA_WORDS", "")
# Members with Manage Messages (mods/admins) are exempt when this is on.
PROFANITY_BYPASS_MODS: bool = os.getenv("PROFANITY_BYPASS_MODS", "true").strip().lower() in {"1", "true", "yes"}
# Strike system: this many strikes inside the rolling window → timeout.
PROFANITY_STRIKE_LIMIT: int = _int("PROFANITY_STRIKE_LIMIT", 3)
# Rolling window strikes are counted over (seconds). Default 1 hour.
PROFANITY_STRIKE_WINDOW_SECONDS: int = _int("PROFANITY_STRIKE_WINDOW_SECONDS", 3600)
# How long (seconds) the member is muted once they hit the strike limit. Default 15 min.
PROFANITY_MUTE_SECONDS: int = _int("PROFANITY_MUTE_SECONDS", 900)

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
# Optional role name that gates the control commands (skip/stop/pause/loop/…) so
# only DJs (or mods) can touch others' music. Blank = anyone can control.
MUSIC_DJ_ROLE: str = os.getenv("MUSIC_DJ_ROLE", "").strip()
# Allow the persistent 24/7 mode (/247) that keeps the bot in the VC and rejoins
# after a restart or disconnect. Set false to forbid it.
MUSIC_247_ALLOWED: bool = os.getenv("MUSIC_247_ALLOWED", "true").strip().lower() in {"1", "true", "yes"}
# FFmpeg audio filter chain for Discord output. The default resamples cleanly to
# Discord's 48 kHz stereo target and limits peaks that can buzz on phone speakers.
MUSIC_AUDIO_FILTER: str = os.getenv(
    "MUSIC_AUDIO_FILTER",
    "aresample=48000:resampler=soxr:precision=28,alimiter=limit=0.95"
).strip()
# Optional low-frequency tremolo rate. This does not change the user's device
# sample rate; it applies an FFmpeg filter to the music signal. Default 0 = off.
MUSIC_TREMOLO_HZ: float = _float("MUSIC_TREMOLO_HZ", 4.0)

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

# Private seven-deadly-sins correction nudges
SEVEN_SINS_DM_ENABLED: bool = os.getenv("SEVEN_SINS_DM_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
SEVEN_SINS_COOLDOWN_SECONDS: int = _int("SEVEN_SINS_COOLDOWN_SECONDS", 21600)

# ── Voice (Gemini text-to-speech) ────────────────────────────────────────
GEMINI_TTS_MODEL: str = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts").strip()
# Prebuilt Gemini voice (Kore, Puck, Aoede, Leda, Zephyr, Charon, Fenrir, …).
GEMINI_TTS_VOICE: str = os.getenv("GEMINI_TTS_VOICE", "Kore").strip()
# ── Two-way voice timing (tune for snappiness) ───────────────────────────
# Silence (ms) after you stop talking before she replies. Lower = snappier,
# but too low cuts you off mid-sentence.
VOICE_SILENCE_MS: int = _int("VOICE_SILENCE_MS", 700)
# Ignore blips shorter than this (ms).
VOICE_MIN_MS: int = _int("VOICE_MIN_MS", 450)
# Keep voice replies short so they generate + speak fast.
VOICE_REPLY_TOKENS: int = _int("VOICE_REPLY_TOKENS", 120)
# Model for understanding your speech (a faster model = lower latency).
VOICE_MODEL: str = os.getenv("VOICE_MODEL", "gemini-2.0-flash").strip()

# ── YouTube + knowledge reports ──────────────────────────────────────────
# Optional YouTube Data API v3 key for /youtube search (real video links).
YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "").strip()
# Public channel where /learn posts knowledge / intelligence reports.
KNOWLEDGE_CHANNEL: str = os.getenv("KNOWLEDGE_CHANNEL", "knowledge").strip()

# ── Phase 2: persistence + scheduled/stateful features ───────────────────
DATA_CHANNEL: str = os.getenv("DATA_CHANNEL", "zafven-data").strip()

# Initiation ranks (activity XP -> roles)
RANKS_ENABLED: bool = os.getenv("RANKS_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
RANK_COOLDOWN_SECONDS: int = _int("RANK_COOLDOWN_SECONDS", 60)
# Role ladder as "RoleName:level" pairs; level = floor(sqrt(xp/100)).
RANK_LADDER: list[str] = _csv("RANK_LADDER", "Helper:1,Regular:3,Trusted:6,Steward:10,Elder:15")

# Daily broadcast is disabled by default; the former occult transit/oracle cog is
# no longer loaded at startup.
DAILY_ENABLED: bool = os.getenv("DAILY_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
DAILY_CHANNEL: str = os.getenv("DAILY_CHANNEL", "daily").strip()
DAILY_HOUR_UTC: int = _int("DAILY_HOUR_UTC", 13)


def validate() -> list[str]:
    """Return a list of fatal config problems (empty == OK)."""
    problems = []
    if not TOKEN:
        problems.append("DISCORD_TOKEN is not set.")
    if not GEMINI_API_KEY:
        problems.append("GEMINI_API_KEY is not set (Gemini is required for readings).")
    if GEMINI_WEB_SEARCH not in {"auto", "on", "off"}:
        problems.append("GEMINI_WEB_SEARCH must be one of: auto, on, off.")
    return problems
