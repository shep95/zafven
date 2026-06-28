"""File-safety helpers: dangerous extensions + optional VirusTotal hash lookup.

Malware can't be truly "scanned" without an AV engine, so the reliable defenses
are (1) blocking executable/script file types and (2) checking the file's SHA-256
against VirusTotal's known-malware database (hash only — the file is never
uploaded). NSFW image classification is done separately via the Gemini gateway.
"""
from __future__ import annotations

import hashlib
import logging

import aiohttp

import config

log = logging.getLogger("zafven.filesafety")

# Executable / script types commonly used to deliver malware on Discord.
DEFAULT_BLOCKED = {
    "exe", "scr", "bat", "cmd", "com", "pif", "vbs", "vbe", "js", "jse", "jar",
    "msi", "msp", "ps1", "psm1", "apk", "app", "dll", "sh", "bash", "cpl", "hta",
    "wsf", "wsh", "reg", "lnk", "gadget", "inf", "iso", "img",
}


def _blocked() -> set[str]:
    extra = {e.lower().lstrip(".") for e in config.BLOCKED_EXTENSIONS}
    return DEFAULT_BLOCKED | extra


def is_blocked_file(filename: str) -> bool:
    name = filename.lower()
    dot = name.rfind(".")
    return dot != -1 and name[dot + 1:] in _blocked()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def virustotal_malicious(file_hash: str) -> bool | None:
    """True if VirusTotal flags the hash as malicious, False if clean, None if unknown."""
    if not config.VIRUSTOTAL_API_KEY:
        return None
    url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
    headers = {"x-apikey": config.VIRUSTOTAL_API_KEY}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as s:
            async with s.get(url) as resp:
                if resp.status == 404:
                    return None  # not in VT's database
                if resp.status != 200:
                    log.info("VirusTotal %s for %s", resp.status, file_hash[:12])
                    return None
                data = await resp.json()
                stats = data["data"]["attributes"]["last_analysis_stats"]
                return int(stats.get("malicious", 0)) > 0
    except (aiohttp.ClientError, KeyError, Exception) as exc:  # noqa: BLE001
        log.info("VirusTotal lookup failed: %s", exc)
        return None
