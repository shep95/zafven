"""Bible reference detection and lookup through public-domain translations."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

import config


BOOKS = (
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
    "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles",
    "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalm", "Psalms",
    "Proverbs", "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah",
    "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
    "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans",
    "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians", "Philippians",
    "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy",
    "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John",
    "2 John", "3 John", "Jude", "Revelation",
)

BOOK_ALT = {
    "Gen": "Genesis", "Ex": "Exodus", "Exod": "Exodus", "Lev": "Leviticus",
    "Num": "Numbers", "Deut": "Deuteronomy", "Josh": "Joshua", "Judg": "Judges",
    "Ps": "Psalms", "Prov": "Proverbs", "Eccl": "Ecclesiastes", "Song": "Song of Solomon",
    "Song Songs": "Song of Solomon", "Isa": "Isaiah", "Jer": "Jeremiah",
    "Lam": "Lamentations", "Ezek": "Ezekiel", "Dan": "Daniel", "Hos": "Hosea",
    "Obad": "Obadiah", "Mic": "Micah", "Nah": "Nahum", "Hab": "Habakkuk",
    "Zeph": "Zephaniah", "Hag": "Haggai", "Zech": "Zechariah", "Mal": "Malachi",
    "Matt": "Matthew", "Mk": "Mark", "Jn": "John", "Rom": "Romans",
    "1 Cor": "1 Corinthians", "2 Cor": "2 Corinthians", "Gal": "Galatians",
    "Eph": "Ephesians", "Phil": "Philippians", "Col": "Colossians",
    "1 Thess": "1 Thessalonians", "2 Thess": "2 Thessalonians",
    "1 Tim": "1 Timothy", "2 Tim": "2 Timothy", "Heb": "Hebrews",
    "Jas": "James", "Rev": "Revelation",
}

_BOOK_PATTERN = "|".join(
    re.escape(b) for b in sorted([*BOOKS, *BOOK_ALT], key=len, reverse=True)
)
REFERENCE_RE = re.compile(
    rf"\b(?P<book>{_BOOK_PATTERN})\.?\s+(?P<chapter>\d{{1,3}})(?::(?P<verses>\d{{1,3}}(?:\s*[-,]\s*\d{{1,3}})?))?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Passage:
    reference: str
    translation: str
    text: str


def find_references(text: str, *, limit: int = 2) -> list[str]:
    """Return normalized Bible references mentioned in free text."""
    refs: list[str] = []
    seen: set[str] = set()
    for match in REFERENCE_RE.finditer(text):
        book_raw = re.sub(r"\s+", " ", match.group("book").replace(".", "")).strip()
        book = BOOK_ALT.get(book_raw.title(), book_raw.title())
        chapter = match.group("chapter")
        verses = (match.group("verses") or "").replace(" ", "")
        ref = f"{book} {chapter}:{verses}" if verses else f"{book} {chapter}"
        key = ref.lower()
        if key not in seen:
            refs.append(ref)
            seen.add(key)
        if len(refs) >= limit:
            break
    return refs


async def fetch_passages(reference: str, translations: list[str] | None = None) -> list[Passage]:
    """Fetch a reference in several public-domain/open translations."""
    wanted = translations or config.BIBLE_TRANSLATIONS
    timeout = aiohttp.ClientTimeout(total=config.BIBLE_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [_fetch_one(session, reference, t.strip().lower()) for t in wanted if t.strip()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return [p for p in results if isinstance(p, Passage) and p.text]


async def _fetch_one(session: aiohttp.ClientSession, reference: str, translation: str) -> Passage | None:
    encoded = quote(reference)
    url = f"https://bible-api.com/{encoded}?translation={quote(translation)}"
    async with session.get(url, headers={"Accept": "application/json"}) as resp:
        if resp.status != 200:
            return None
        data: Any = await resp.json(content_type=None)
    text = re.sub(r"\s+", " ", str(data.get("text") or "")).strip()
    if not text:
        return None
    name = data.get("translation_name") or data.get("translation_id") or translation.upper()
    ref = data.get("reference") or reference
    return Passage(reference=str(ref), translation=str(name), text=text)
