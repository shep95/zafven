"""Fetch a media file from a pasted URL so it can be re-uploaded to Discord.

Pulls direct image/video/gif files, or a web page's preview media (og:image /
og:video / twitter:image). Security: only http(s), blocks private/loopback/
reserved IPs (SSRF guard), caps size, and limits redirects. It does NOT scrape
or rip platform videos behind players — paste a direct media link for those.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import mimetypes
import os
import re
from urllib.parse import urljoin, urlparse

import aiohttp

log = logging.getLogger("zafven.media")

_MEDIA_PREFIXES = ("image/", "video/")
_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)\s*=\s*["\'](?:og:image|og:image:url|og:video|og:video:url|twitter:image)["\']'
    r'[^>]*?content\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_OG_RE_ALT = re.compile(
    r'<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]*?(?:property|name)\s*=\s*'
    r'["\'](?:og:image|og:image:url|og:video|og:video:url|twitter:image)["\']', re.IGNORECASE)


class MediaError(Exception):
    pass


def _ip_ok(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (ip.is_private or ip.is_loopback or ip.is_reserved
                or ip.is_link_local or ip.is_multicast or ip.is_unspecified)


async def _host_safe(host: str | None) -> bool:
    if not host:
        return False
    try:
        infos = await asyncio.get_event_loop().getaddrinfo(host, None)
    except Exception:  # noqa: BLE001
        return False
    return bool(infos) and all(_ip_ok(info[4][0]) for info in infos)


def _filename(url: str, content_type: str) -> str:
    name = os.path.basename(urlparse(url).path) or "file"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if "." not in name:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".bin"
        name += ext
    return name


async def grab(url: str, max_bytes: int) -> tuple[str, bytes, str]:
    """Return (filename, data, content_type) for the media at url, or raise MediaError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise MediaError("Only http(s) links are supported.")
    if not await _host_safe(parsed.hostname):
        raise MediaError("That host isn't allowed.")

    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (zafven media grab)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
        return await _fetch(s, url, max_bytes, depth=0)


async def _fetch(s: aiohttp.ClientSession, url: str, max_bytes: int, depth: int) -> tuple[str, bytes, str]:
    if depth > 1:
        raise MediaError("Couldn't find a direct media file on that page.")
    try:
        async with s.get(url, max_redirects=5) as resp:
            # Re-check the final host after any redirects (SSRF).
            if not await _host_safe(urlparse(str(resp.url)).hostname):
                raise MediaError("That host isn't allowed.")
            if resp.status != 200:
                raise MediaError(f"The link returned status {resp.status}.")
            ct = (resp.headers.get("Content-Type") or "").lower()

            if ct.startswith(_MEDIA_PREFIXES):
                data = await _read_capped(resp, max_bytes)
                return _filename(str(resp.url), ct), data, ct

            if "text/html" in ct or ct == "":
                html = (await resp.content.read(1_000_000)).decode("utf-8", errors="replace")
                media_url = _find_og_media(html)
                if not media_url:
                    raise MediaError("No downloadable image/video found at that link.")
                return await _fetch(s, urljoin(str(resp.url), media_url), max_bytes, depth + 1)

            raise MediaError("That link isn't an image or video.")
    except aiohttp.ClientError as exc:
        raise MediaError(f"Couldn't reach that link ({exc.__class__.__name__}).") from exc


async def _read_capped(resp: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(64 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise MediaError(f"That file is over the {max_bytes // (1024 * 1024)} MB upload limit.")
    if not buf:
        raise MediaError("The file was empty.")
    return bytes(buf)


def _find_og_media(html: str) -> str | None:
    m = _OG_RE.search(html) or _OG_RE_ALT.search(html)
    return m.group(1) if m else None
