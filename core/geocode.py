"""Resolve a birth *place* the user types in into coordinates + timezone.

Geocoding the birthplace city for a natal chart is standard astrology — it uses
only what the user supplies, not anyone's live location. Uses OpenStreetMap's
free Nominatim (no key) for lat/lon and timezonefinder for the IANA timezone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

import config

log = logging.getLogger("zafven.geocode")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "zafven-discord-bot/1.0 (astrology birth charts)"

_tf = None  # lazily-initialised TimezoneFinder


@dataclass
class Place:
    lat: float
    lon: float
    display: str
    tz_name: str | None


async def lookup(query: str) -> Place | None:
    """Geocode a place string to coordinates + timezone, or None if not found."""
    params = {"q": query, "format": "json", "limit": "1"}
    timeout = aiohttp.ClientTimeout(total=config.GEMINI_TIMEOUT)
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _USER_AGENT}, timeout=timeout) as s:
            async with s.get(NOMINATIM_URL, params=params) as resp:
                if resp.status != 200:
                    log.warning("Nominatim %s for %r", resp.status, query)
                    return None
                data = await resp.json()
    except (aiohttp.ClientError, Exception) as exc:  # noqa: BLE001
        log.warning("Geocode failed for %r: %s", query, exc)
        return None

    if not data:
        return None
    top = data[0]
    lat, lon = float(top["lat"]), float(top["lon"])
    return Place(lat=lat, lon=lon, display=top.get("display_name", query), tz_name=_timezone_at(lat, lon))


def _timezone_at(lat: float, lon: float) -> str | None:
    global _tf
    try:
        if _tf is None:
            from timezonefinder import TimezoneFinder
            _tf = TimezoneFinder()
        return _tf.timezone_at(lat=lat, lng=lon)
    except Exception as exc:  # noqa: BLE001 — package missing or lookup failed
        log.info("Timezone lookup unavailable (%s); will fall back to longitude estimate.", exc)
        return None
