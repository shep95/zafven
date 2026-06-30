"""ModelGateway — the single, provider-agnostic door to the Gemini LLM.

Per the Aureon Coding Rules: all model interactions are abstracted behind one
interface with strict timeouts, bounded tokens, retry-with-backoff, and no
hardcoded secrets. Uses Google's native `generateContent` API, which is
multimodal (text + image) and supports Google Search grounding as a tool.

This gateway is REQUIRED — if it can't reach Gemini, the calling command
surfaces an honest error rather than inventing a result.
"""
from __future__ import annotations

import asyncio
import base64
import logging

import aiohttp

import config

log = logging.getLogger("zafven.gateway")


class GatewayError(RuntimeError):
    """Raised when Gemini cannot produce a usable response."""


class ModelGateway:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "x-goog-api-key": config.GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=config.GEMINI_TIMEOUT),
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def narrate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_bytes: bytes | None = None,
        image_mime: str | None = None,
        web_search: bool | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generate text. `web_search=None` defers to the configured default."""
        if self._session is None or self._session.closed:
            await self.start()

        parts: list[dict] = [{"text": user_prompt}]
        if image_bytes is not None:
            parts.append({
                "inline_data": {
                    "mime_type": image_mime or "image/png",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            })

        generation_config: dict = {
            "temperature": 0.85 if temperature is None else temperature,
            "maxOutputTokens": max_tokens or config.GEMINI_MAX_TOKENS,
        }
        # Disable/limit "thinking" so it doesn't consume the answer's token budget
        # (which truncates replies mid-sentence on 2.5 models).
        if config.GEMINI_THINKING_BUDGET >= 0:
            generation_config["thinkingConfig"] = {"thinkingBudget": config.GEMINI_THINKING_BUDGET}

        payload: dict = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
            "safetySettings": [
                {"category": c, "threshold": config.GEMINI_SAFETY}
                for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                          "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
            ],
        }
        if self._wants_search(web_search):
            payload["tools"] = [{"google_search": {}}]

        return await self._post_with_retry(payload, model=model)

    async def council(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        constraints: str = "",
        candidates: int = 3,
        web_search: bool | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        """Superposition & collapse: generate several diverse candidate answers,
        then run an adversarial oracle that eliminates the weak and ships the
        single survivor. A real best-of-N with LLM-as-critic selection."""
        n = max(2, min(candidates, 4))
        temps = [0.35, 0.8, 1.05, 0.6][:n]

        async def _one(temp: float) -> str:
            try:
                return await self.narrate(
                    system_prompt, user_prompt, web_search=web_search,
                    max_tokens=max_tokens, model=model, temperature=temp)
            except GatewayError:
                return ""

        results = await asyncio.gather(*[_one(t) for t in temps])
        pool = [c.strip() for c in results if c and c.strip()]
        if not pool:
            raise GatewayError("No candidate answers survived generation.")
        if len(pool) == 1:
            return pool[0]

        joined = "\n\n".join(f"=== CANDIDATE {i + 1} ===\n{c}" for i, c in enumerate(pool))
        judge_prompt = (
            f"USER'S QUESTION:\n{user_prompt}\n\n"
            f"HARD CONSTRAINTS (must hold):\n{constraints or '(infer them from the question)'}\n\n"
            f"COMPETING CANDIDATE ANSWERS:\n{joined}\n\n"
            "Run the collapse: attack each candidate against the question and constraints, "
            "eliminate the weak or wrong ones, then output ONLY the single strongest final "
            "answer (merge real strengths if useful). No scorecards, no commentary about the "
            "candidates — just the surviving answer."
        )
        return await self.narrate(
            system_prompt, judge_prompt, web_search=False,
            max_tokens=max_tokens, model=model, temperature=0.2)

    async def tts(self, text: str, voice: str | None = None) -> tuple[bytes, int]:
        """Synthesize speech via Gemini TTS. Returns (raw PCM 16-bit LE mono, sample_rate)."""
        if self._session is None or self._session.closed:
            await self.start()
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice or config.GEMINI_TTS_VOICE}
                    }
                },
            },
        }
        url = f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_TTS_MODEL}:generateContent"
        assert self._session is not None
        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                raise GatewayError(f"Gemini TTS {resp.status}: {(await resp.text())[:300]}")
            data = await resp.json()
        try:
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"Malformed Gemini TTS response: {exc}") from exc
        rate = 24000
        mime = part.get("mimeType", "")
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except ValueError:
                pass
        if not pcm:
            raise GatewayError("Gemini TTS returned no audio.")
        return pcm, rate

    def _wants_search(self, web_search: bool | None) -> bool:
        if web_search is True:
            return True
        if web_search is False:
            return False
        return config.GEMINI_WEB_SEARCH in {"auto", "on"}

    async def _post_with_retry(self, payload: dict, attempts: int = 3, model: str | None = None) -> str:
        url = f"{config.GEMINI_BASE_URL}/models/{model or config.GEMINI_MODEL}:generateContent"
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                assert self._session is not None
                async with self._session.post(url, json=payload) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        raise GatewayError(f"Gemini transient {resp.status}")
                    if resp.status != 200:
                        body = await resp.text()
                        raise GatewayError(f"Gemini {resp.status}: {body[:300]}")
                    data = await resp.json()
                    return self._extract(data)
            except (aiohttp.ClientError, asyncio.TimeoutError, GatewayError) as exc:
                last_err = exc
                if attempt < attempts:
                    backoff = 1.5 * attempt
                    log.warning("Gemini attempt %d failed (%s); retrying in %.1fs", attempt, exc, backoff)
                    await asyncio.sleep(backoff)
        raise GatewayError(f"Gemini unreachable after {attempts} attempts: {last_err}")

    @staticmethod
    def _extract(data: dict) -> str:
        # Prompt-level block (safety / recitation) → no candidates.
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise GatewayError(f"Gemini blocked the prompt: {feedback['blockReason']}")

        candidates = data.get("candidates") or []
        if not candidates:
            raise GatewayError("Gemini returned no candidates.")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(
            p["text"] for p in parts
            if isinstance(p, dict) and "text" in p and not p.get("thought")
        ).strip()
        if not text:
            reason = candidates[0].get("finishReason", "unknown")
            raise GatewayError(f"Gemini returned an empty result (finishReason={reason}).")
        return text
