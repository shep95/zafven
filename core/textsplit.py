"""Split long text into Discord-safe chunks on clean boundaries."""
from __future__ import annotations

LIMIT = 2000


def chunk(text: str, limit: int = LIMIT, max_chunks: int = 6) -> list[str]:
    """Break text into <=limit pieces, preferring newline/space boundaries."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit and len(chunks) < max_chunks - 1:
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if remaining:
        chunks.append(remaining[:limit])
    return chunks
