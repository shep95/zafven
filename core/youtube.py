"""YouTube helpers: parse links, fetch transcripts, and (optionally) search.

Transcripts use youtube-transcript-api (no key, but YouTube may rate-limit
datacenter IPs — failures are handled gracefully). Search uses the YouTube Data
API v3 when YOUTUBE_API_KEY is set, returning real, verified video links.
"""
from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

import config

log = logging.getLogger("zafven.youtube")

_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def extract_video_id(text: str) -> str | None:
    m = _ID_RE.search(text)
    return m.group(1) if m else None


async def fetch_transcript(video_id: str) -> str | None:
    """Return the transcript text for a video, or None if unavailable."""
    def _grab() -> str | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            parts = YouTubeTranscriptApi.get_transcript(video_id)
            return " ".join(p["text"] for p in parts if p.get("text"))
        except Exception as exc:  # noqa: BLE001 — no captions / blocked / not found
            log.info("Transcript fetch failed for %s: %s", video_id, exc)
            return None
    return await asyncio.to_thread(_grab)


async def search(query: str, max_results: int = 5) -> list[dict] | None:
    """Search YouTube via the Data API. None if no key; [] if no results."""
    if not config.YOUTUBE_API_KEY:
        return None
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": config.YOUTUBE_API_KEY, "q": query, "part": "snippet",
        "type": "video", "maxResults": str(max_results),
    }
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, params=params) as resp:
                if resp.status != 200:
                    log.warning("YouTube search %s: %s", resp.status, (await resp.text())[:200])
                    return []
                data = await resp.json()
    except (aiohttp.ClientError, Exception) as exc:  # noqa: BLE001
        log.warning("YouTube search failed: %s", exc)
        return []
    out = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        sn = item.get("snippet", {})
        if vid:
            out.append({
                "title": sn.get("title", "video"),
                "channel": sn.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
    return out
