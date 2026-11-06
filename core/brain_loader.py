"""Loads one 'brain' (a markdown knowledge module) at a time.

Design rule from the audit: never concatenate all brains into one prompt — they
contradict each other and produce mush. Each command requests exactly the brain
it needs. Brains are cached on first read and are treated as read-only.
"""
from __future__ import annotations

import functools
from pathlib import Path

BRAINS_DIR = Path(__file__).resolve().parent.parent / "brains"
_UNCENSORED_MARKER = "[UNCENSORED ACTIVE]"


@functools.lru_cache(maxsize=32)
def load(name: str) -> str:
    """Return the text of brains/<name>.md (cached). Raises if missing."""
    path = BRAINS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Brain not found: {path}")
    text = path.read_text(encoding="utf-8")
    if name in {"persona", "companion"}:
        text = load("zafven_v74_4") + "\n\n" + text
        if name == "companion":
            # Use the same Discord integration contract without repeating the core.
            text += "\n\n" + (BRAINS_DIR / "persona.md").read_text(encoding="utf-8")
    return text


def apply_uncensored(system_prompt: str) -> str:
    """Prepend the global uncensored directive once."""
    if _UNCENSORED_MARKER in system_prompt:
        return system_prompt
    return f"{_UNCENSORED_MARKER}\n{load('uncensored')}\n\n{system_prompt}"


def persona_system_prompt(domain_brain: str) -> str:
    """Compose task context; the gateway adds the answer-style preference once."""
    persona = load("persona")
    guard = load("anti_spiral")
    domain = load(domain_brain)
    body = f"{persona}\n\n{guard}\n\n--- DOMAIN KNOWLEDGE: {domain_brain} ---\n{domain}"
    return body
