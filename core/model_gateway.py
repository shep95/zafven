"""ModelGateway — the single, provider-agnostic door to the LLM (Mistral).

All model interactions are abstracted behind one interface with strict timeouts,
bounded tokens, retry-with-backoff, and no hardcoded secrets. Uses Mistral's
OpenAI-compatible `/v1/chat/completions` API. Vision (image input) routes to a
Pixtral model automatically when image bytes are supplied.

Notes vs. the previous Gemini backend:
  • `web_search` is accepted for call-site compatibility but is a no-op — Mistral
    has no built-in Google-Search grounding. The model answers from its own
    knowledge; callers that need live facts should pass them in the prompt.
  • `tts()` raises GatewayError — Mistral has no text-to-speech. Spoken-voice
    features stay disabled until a dedicated TTS provider is wired in.

This gateway is REQUIRED — if it can't reach Mistral, the calling command surfaces
an honest error rather than inventing a result.
"""
from __future__ import annotations

import asyncio
import base64
import logging

import aiohttp

import config
from core.brain_loader import apply_uncensored

log = logging.getLogger("zafven.gateway")


class GatewayError(RuntimeError):
    """Raised when the model cannot produce a usable response."""


class ModelGateway:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._session: aiohttp.ClientSession | None = None
        # Optional overrides let a second gateway run on a user-supplied credential
        # (see intelligence.gateway) without touching the built-in one. Defaults keep
        # every existing `ModelGateway()` caller on the configured Mistral key.
        self._api_key = (api_key or config.MISTRAL_API_KEY).strip()
        self._base_url = (base_url or config.MISTRAL_BASE_URL).strip().rstrip("/")
        self._model_default = (model or config.MISTRAL_MODEL).strip()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=config.MISTRAL_TIMEOUT),
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
        web_search: bool | None = None,   # accepted for compatibility; no-op on Mistral
        max_tokens: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        uncensored: bool = True,
    ) -> str:
        """Generate text (optionally about an image). Returns the reply string."""
        if self._session is None or self._session.closed:
            await self.start()

        if config.UNCENSORED_MODE and uncensored:
            system_prompt = apply_uncensored(system_prompt)

        # Build the user turn. With an image, Mistral expects a content array and a
        # vision-capable model (Pixtral); route there automatically.
        chosen_model = model or self._model_default
        if image_bytes is not None:
            data_uri = f"data:{image_mime or 'image/png'};base64," + base64.b64encode(image_bytes).decode("ascii")
            user_content: object = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": data_uri},
            ]
            if model is None:
                chosen_model = config.MISTRAL_VISION_MODEL
        else:
            user_content = user_prompt

        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.85 if temperature is None else temperature,
            "max_tokens": max_tokens or config.MISTRAL_MAX_TOKENS,
        }
        return await self._post_with_retry(payload)

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
        """Text-to-speech is not available on Mistral. Spoken-voice features stay
        disabled until a dedicated TTS provider is configured (config.TTS_*)."""
        raise GatewayError(
            "text-to-speech is not configured — the brain runs on Mistral, which has no "
            "TTS. add a TTS provider (config.TTS_*) to enable spoken voice.")

    async def _post_with_retry(self, payload: dict, attempts: int = 3) -> str:
        url = f"{self._base_url}/chat/completions"
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                assert self._session is not None
                async with self._session.post(url, json=payload) as resp:
                    if resp.status == 429 or resp.status >= 500:
                        raise GatewayError(f"Mistral transient {resp.status}")
                    if resp.status != 200:
                        body = await resp.text()
                        raise GatewayError(f"Mistral {resp.status}: {body[:300]}")
                    data = await resp.json()
                    return self._extract(data)
            except (aiohttp.ClientError, asyncio.TimeoutError, GatewayError) as exc:
                last_err = exc
                if attempt < attempts:
                    backoff = 1.5 * attempt
                    log.warning("Mistral attempt %d failed (%s); retrying in %.1fs", attempt, exc, backoff)
                    await asyncio.sleep(backoff)
        raise GatewayError(f"Mistral unreachable after {attempts} attempts: {last_err}")

    @staticmethod
    def _extract(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise GatewayError("Mistral returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        # Mistral may return content as a string or (for some models) a parts list.
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        text = (content or "").strip()
        if not text:
            reason = choices[0].get("finish_reason", "unknown")
            raise GatewayError(f"Mistral returned an empty result (finish_reason={reason}).")
        return text
