"""Loads one 'brain' (a markdown knowledge module) at a time.

Design rule from the audit: never concatenate all brains into one prompt — they
contradict each other and produce mush. Each command requests exactly the brain
it needs. Brains are cached on first read and are treated as read-only.
"""
from __future__ import annotations

import functools
from pathlib import Path

BRAINS_DIR = Path(__file__).resolve().parent.parent / "brains"


@functools.lru_cache(maxsize=32)
def load(name: str) -> str:
    """Return the text of brains/<name>.md (cached). Raises if missing."""
    path = BRAINS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Brain not found: {path}")
    return path.read_text(encoding="utf-8")


def persona_system_prompt(domain_brain: str) -> str:
    """Compose the system prompt: persona + anti-spiral guard + the domain brain."""
    persona = load("persona")
    guard = load("anti_spiral")
    domain = load(domain_brain)
    return f"{persona}\n\n{guard}\n\n--- DOMAIN KNOWLEDGE: {domain_brain} ---\n{domain}"
