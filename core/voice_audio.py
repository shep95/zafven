"""Wrap raw PCM (from Gemini TTS) into a WAV container FFmpeg/Discord can play."""
from __future__ import annotations

import io
import wave


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
