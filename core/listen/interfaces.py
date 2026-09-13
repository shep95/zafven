"""Isolated probabilistic-engine interfaces (§4).

The deterministic core never does inference itself. Transcription, diarization,
language ID, translation, and environmental-sound classification are probabilistic,
so they live behind these ports. The default is a NullEngine that returns UNKNOWN /
"unavailable" — the platform therefore NEVER fabricates a transcript or a speaker
label when no real engine is plugged in (§87: state the limitation, don't fake it).

To make the platform actually transcribe, register a concrete engine (e.g. a
Whisper server, a diarization service) via `EngineRegistry`. Those are external
dependencies and typically require a separate capture client feeding them audio.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.listen.epistemic import Claim, Epistemic, estimate, unknown


@dataclass
class TranscriptResult:
    text: Claim                          # ESTIMATE (model) or UNKNOWN
    language: Claim
    segments: list[dict] = field(default_factory=list)


class TranscriptionEngine:
    """Port: audio bytes → text. Concrete impls wrap an external ASR service."""
    name = "null"

    def available(self) -> bool:
        return False

    def transcribe(self, audio_ref: str, *, sample_rate: int = 16000) -> TranscriptResult:  # pragma: no cover
        raise NotImplementedError


class DiarizationEngine:
    name = "null"

    def available(self) -> bool:
        return False

    def diarize(self, audio_ref: str) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


class LanguageDetector:
    name = "null"

    def available(self) -> bool:
        return False

    def detect(self, text: str) -> Claim:  # pragma: no cover
        raise NotImplementedError


class Translator:
    name = "null"

    def available(self) -> bool:
        return False

    def translate(self, text: str, target: str) -> Claim:  # pragma: no cover
        raise NotImplementedError


class EnvironmentClassifier:
    name = "null"

    def available(self) -> bool:
        return False

    def classify(self, audio_ref: str) -> list[Claim]:  # pragma: no cover
        raise NotImplementedError


# ---- Null engines: honest "unavailable", never fabricated output ----------
class NullTranscription(TranscriptionEngine):
    def transcribe(self, audio_ref: str, *, sample_rate: int = 16000) -> TranscriptResult:
        return TranscriptResult(
            text=unknown("no transcription engine configured"),
            language=unknown("no language detector configured"))


class NullDiarization(DiarizationEngine):
    def diarize(self, audio_ref: str) -> list[dict]:
        return []


class NullLanguage(LanguageDetector):
    def detect(self, text: str) -> Claim:
        return unknown("no language detector configured")


class NullTranslator(Translator):
    def translate(self, text: str, target: str) -> Claim:
        return unknown("no translation engine configured")


class NullEnvironment(EnvironmentClassifier):
    def classify(self, audio_ref: str) -> list[Claim]:
        return []


@dataclass
class EngineRegistry:
    """Holds the active engines. Defaults to null engines so nothing is fabricated.
    Swap in real engines to enable actual transcription/diarization/etc."""
    transcription: TranscriptionEngine = field(default_factory=NullTranscription)
    diarization: DiarizationEngine = field(default_factory=NullDiarization)
    language: LanguageDetector = field(default_factory=NullLanguage)
    translator: Translator = field(default_factory=NullTranslator)
    environment: EnvironmentClassifier = field(default_factory=NullEnvironment)

    def status(self) -> dict[str, bool]:
        return {
            "transcription": self.transcription.available(),
            "diarization": self.diarization.available(),
            "language": self.language.available(),
            "translation": self.translator.available(),
            "environment": self.environment.available(),
        }

    def any_available(self) -> bool:
        return any(self.status().values())
