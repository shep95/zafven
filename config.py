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
GUILD_ID: int | None = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID", "").strip() else None
MEMBER_LOG_CHANNEL: str = os.getenv("MEMBER_LOG_CHANNEL", "member-log").strip()
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
GEMINI_MAX_TOKENS: int = _int("GEMINI_MAX_TOKENS", 1200)
GEMINI_TIMEOUT: int = _int("GEMINI_TIMEOUT", 45)
GEMINI_WEB_SEARCH: str = os.getenv("GEMINI_WEB_SEARCH", "auto").strip().lower()

# ── Paywall / premium gating ─────────────────────────────────────────────
# Reading commands require ONE of: a configured premium role, a valid Discord
# app-subscription entitlement (PREMIUM_SKU_ID), or admin bypass.
PREMIUM_ROLES: list[str] = [r.lower() for r in _csv("PREMIUM_ROLES", "Premium")]
PREMIUM_SKU_ID: int | None = int(os.getenv("PREMIUM_SKU_ID")) if os.getenv("PREMIUM_SKU_ID", "").strip() else None
PREMIUM_BYPASS_ADMIN: bool = os.getenv("PREMIUM_BYPASS_ADMIN", "true").strip().lower() in {"1", "true", "yes"}
SUBSCRIBE_URL: str = os.getenv("SUBSCRIBE_URL", "").strip()


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
