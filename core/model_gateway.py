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

        payload: dict = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.85,
                "maxOutputTokens": max_tokens or config.GEMINI_MAX_TOKENS,
            },
        }
        if self._wants_search(web_search):
            payload["tools"] = [{"google_search": {}}]

        return await self._post_with_retry(payload)

    def _wants_search(self, web_search: bool | None) -> bool:
        if web_search is True:
            return True
        if web_search is False:
            return False
        return config.GEMINI_WEB_SEARCH in {"auto", "on"}

    async def _post_with_retry(self, payload: dict, attempts: int = 3) -> str:
        url = f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_MODEL}:generateContent"
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
        text = "".join(p["text"] for p in parts if isinstance(p, dict) and "text" in p).strip()
        if not text:
            reason = candidates[0].get("finishReason", "unknown")
            raise GatewayError(f"Gemini returned an empty result (finishReason={reason}).")
        return text
