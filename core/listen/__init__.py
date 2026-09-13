"""Deterministic acoustic-observation control layer for zafven.

This package is the bot-side (control + storage + search + audit) of the audio
platform described in the build spec. It is deterministic and does NOT capture or
transcribe audio itself:

  • microphone capture happens in a SEPARATE capture client (a bot cannot read your
    mic) — the client authenticates, shows a recording indicator, and ingests
    transcripts/events here;
  • transcription/diarization/translation/classification are probabilistic and live
    behind interfaces.py, defaulting to null engines that return UNKNOWN so nothing
    is ever fabricated.

See docs/LISTEN_ARCHITECTURE.md for the full architecture, model audit, and the
honest list of what is external / legally variable / not yet implemented.
"""
from __future__ import annotations

from core.listen.controller import ListenController
from core.listen.interfaces import EngineRegistry

# Process-wide engine registry. Null by default; swap in real engines to enable
# actual transcription/diarization/etc. (external dependencies).
ENGINES = EngineRegistry()

__all__ = ["ListenController", "EngineRegistry", "ENGINES"]
