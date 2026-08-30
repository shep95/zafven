"""Resolve a YouTube (or search) query into a streamable audio track via yt-dlp.

Extraction is blocking, so it's run in a thread. We ask yt-dlp for the best audio
stream and hand its direct URL to FFmpeg — nothing is downloaded to disk. On cloud
hosts YouTube sometimes demands a sign-in ("confirm you're not a bot"); set
MUSIC_COOKIE_FILE to a cookies.txt export to get past that.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import config

log = logging.getLogger("zafven.music")

# Reconnect so a transient network blip mid-song doesn't kill playback.
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"


@dataclass
class Track:
    title: str
    webpage_url: str
    stream_url: str
    duration: int          # seconds (0 if unknown / live)
    uploader: str
    thumbnail: str | None
    requester: str         # display name of whoever queued it


def _ytdl_opts() -> dict:
    opts: dict = {
        "format": "bestaudio/best",
        "noplaylist": True,          # a radio/mix/playlist link resolves to its single video
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",  # bare words → YouTube search
        "source_address": "0.0.0.0",
        "cachedir": False,
        # The android player client dodges most datacenter "sign in" bot checks.
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    if config.MUSIC_COOKIE_FILE:
        opts["cookiefile"] = config.MUSIC_COOKIE_FILE
    return opts


def _extract(query: str) -> dict | None:
    import yt_dlp  # imported lazily so the bot boots even if yt-dlp isn't installed
    with yt_dlp.YoutubeDL(_ytdl_opts()) as ydl:
        info = ydl.extract_info(query, download=False)
    if not info:
        return None
    if "entries" in info:  # search results / playlist → take the first real entry
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            return None
        info = entries[0]
    return info


async def resolve(query: str, requester: str) -> Track | None:
    """Return a playable Track for a URL or search string, or None if nothing found."""
    try:
        info = await asyncio.to_thread(_extract, query)
    except Exception as exc:  # noqa: BLE001 — surface a clean failure to the caller
        log.info("music resolve failed for %r: %s", query, exc)
        return None
    if not info or not info.get("url"):
        return None
    return Track(
        title=info.get("title") or "unknown track",
        webpage_url=info.get("webpage_url") or query,
        stream_url=info["url"],
        duration=int(info.get("duration") or 0),
        uploader=info.get("uploader") or info.get("channel") or "",
        thumbnail=info.get("thumbnail"),
        requester=requester,
    )


def fmt_duration(seconds: int) -> str:
    if not seconds:
        return "live / unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
