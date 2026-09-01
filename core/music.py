"""Resolve a YouTube (or search) query into a streamable audio track via yt-dlp.

Extraction is blocking, so it's run in a thread. We ask yt-dlp for the best audio
stream and hand its direct URL to FFmpeg — nothing is downloaded to disk. On cloud
hosts YouTube sometimes demands a sign-in ("confirm you're not a bot"); set
MUSIC_COOKIE_FILE to a cookies.txt export to get past that.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass

import config

log = logging.getLogger("zafven.music")

_cookie_tmp: str | None = None  # cached temp cookies file written from MUSIC_COOKIES


def _cookie_path() -> str:
    """A cookies.txt path from MUSIC_COOKIE_FILE, or one written from MUSIC_COOKIES."""
    global _cookie_tmp
    if config.MUSIC_COOKIE_FILE:
        return config.MUSIC_COOKIE_FILE
    content = config.MUSIC_COOKIES.strip()
    if not content:
        return ""
    if _cookie_tmp and os.path.exists(_cookie_tmp):
        return _cookie_tmp
    try:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="ytcookies_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        _cookie_tmp = path
        return path
    except OSError as exc:
        log.warning("could not write cookies file: %s", exc)
        return ""

# Reconnect so a transient network blip mid-song doesn't kill playback.
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"


def ffmpeg_options() -> str:
    """Build Discord-safe FFmpeg output options from config."""
    filters = [config.MUSIC_AUDIO_FILTER] if config.MUSIC_AUDIO_FILTER else []
    tremolo = max(0, int(getattr(config, "MUSIC_TREMOLO_HZ", 0) or 0))
    if tremolo:
        # Keep the user-requested low-frequency effect bounded. This is a signal
        # filter, not a change to the listener's physical output device.
        filters.append(f"tremolo=f={max(4, min(tremolo, 8))}:d=0.25")
    opts = ["-vn", "-ac 2", "-ar 48000"]
    if filters:
        opts.append(f"-af {','.join(filters)}")
    return " ".join(opts)


@dataclass
class Track:
    title: str
    webpage_url: str
    stream_url: str
    duration: int          # seconds (0 if unknown / live)
    uploader: str
    thumbnail: str | None
    requester: str         # display name of whoever queued it
    requester_id: int = 0  # their Discord user id (for self-skip / DJ checks)


# Player clients to try, in order. `None` = yt-dlp's own maintained default set
# (usually the best). The rest are fallbacks that behave differently under
# YouTube's datacenter bot checks; whichever first yields a stream wins.
_CLIENT_ATTEMPTS: list[list[str] | None] = [None, ["ios"], ["tv"], ["android"], ["web"]]


def _ytdl_opts(player_clients: list[str] | None) -> dict:
    opts: dict = {
        "format": "bestaudio/best",
        "noplaylist": True,          # a radio/mix/playlist link resolves to its single video
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",  # bare words → YouTube search
        "source_address": "0.0.0.0",
        "cachedir": False,
    }
    if player_clients:
        opts["extractor_args"] = {"youtube": {"player_client": player_clients}}
    cookie = _cookie_path()
    if cookie:
        opts["cookiefile"] = cookie
    return opts


def _extract(query: str) -> tuple[dict | None, str | None]:
    """Try each player client until one yields a playable stream. (info, error)."""
    import yt_dlp  # imported lazily so the bot boots even if yt-dlp isn't installed
    last_err: str | None = None
    for clients in _CLIENT_ATTEMPTS:
        try:
            with yt_dlp.YoutubeDL(_ytdl_opts(clients)) as ydl:
                info = ydl.extract_info(query, download=False)
        except Exception as exc:  # noqa: BLE001 — try the next client
            last_err = str(exc)
            continue
        if not info:
            last_err = "no result"
            continue
        if "entries" in info:  # search results / playlist → first real entry
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                last_err = "no matches found"
                continue
            info = entries[0]
        if info.get("url"):
            return info, None
        last_err = "no playable audio stream"
    return None, last_err


async def resolve(query: str, requester: str, requester_id: int = 0) -> tuple["Track | None", str | None]:
    """Resolve a URL/search to a Track. Returns (track, None) or (None, reason)."""
    try:
        info, err = await asyncio.to_thread(_extract, query)
    except Exception as exc:  # noqa: BLE001
        log.info("music resolve crashed for %r: %s", query, exc)
        return None, str(exc)
    if not info:
        log.info("music resolve failed for %r: %s", query, err)
        return None, err
    return Track(
        title=info.get("title") or "unknown track",
        webpage_url=info.get("webpage_url") or query,
        stream_url=info["url"],
        duration=int(info.get("duration") or 0),
        uploader=info.get("uploader") or info.get("channel") or "",
        thumbnail=info.get("thumbnail"),
        requester=requester,
        requester_id=requester_id,
    ), None


def friendly_error(reason: str | None) -> str:
    """Turn a raw yt-dlp error into a short, actionable line for chat."""
    r = (reason or "").lower()
    if "sign in" in r or "not a bot" in r or "confirm you" in r:
        return ("YouTube is blocking this server with a bot check. add a cookies.txt via "
                "`MUSIC_COOKIE_FILE` to fix it (see the README).")
    if "age" in r and "restrict" in r:
        return "that video is age-restricted — YouTube needs a `MUSIC_COOKIE_FILE` (cookies) to play it."
    if "private" in r:
        return "that video is private."
    if "unavailable" in r or "removed" in r or "no matches" in r or "no result" in r:
        return "couldn't find that — try a different link or search terms."
    if "no playable" in r:
        return "found it, but couldn't get a playable audio stream."
    return "couldn't find or load that. try a different link or search."


def fmt_duration(seconds: int) -> str:
    if not seconds:
        return "live / unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
