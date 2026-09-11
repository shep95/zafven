"""Provider-agnostic model gateway + a hard credential boundary.

The model is a replaceable capability, not the intelligence (§5/§20). This module
puts a normalized interface in front of it so the rest of the system never talks to
a provider directly, and so a guild can point zafven at its OWN model key without
the intelligence architecture changing.

Credential boundary (§21/§38): a provider credential is stored in its own namespace,
handed ONLY to the provider that uses it, and NEVER returned to anything that builds
a prompt, a pattern, a memory item, or a log line. The rest of the system works with
a masked reference. Storing a third-party key in Discord-backed storage is opt-in
(PROVIDER_USER_KEYS_ENABLED) and lightly obfuscated at rest — not KMS-grade, and we
say so rather than pretend otherwise.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, asdict

import config
from core.model_gateway import ModelGateway, GatewayError

log = logging.getLogger("zafven.intel.gateway")

_NS_CREDS = "provider_credentials"  # {"provider": str, "model": str, "key_b64": str}


@dataclass
class ModelCapabilities:
    """Normalized capability metadata so the orchestrator routes by what a model can
    actually do (§22), instead of scattering provider quirks through the app."""
    provider: str
    model: str
    text_in: bool = True
    text_out: bool = True
    vision: bool = False
    image_gen: bool = False
    audio_in: bool = False
    audio_out: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    context_window: int = 32000
    coding_suitability: str = "moderate"  # low | moderate | high

    def supports(self, capability: str) -> bool:
        return bool(getattr(self, capability, False))

    def to_dict(self) -> dict:
        return asdict(self)


def _gemini_caps(model: str) -> ModelCapabilities:
    """Best-effort capability profile for a Gemini model id. Conservative defaults;
    a 2.x/2.5 flash/pro is multimodal with tools + grounding."""
    m = (model or "").lower()
    is_pro = "pro" in m
    return ModelCapabilities(
        provider="gemini",
        model=model,
        vision=True,
        image_gen=False,           # this endpoint does text/vision in, not image out
        audio_in=False,
        audio_out=True,            # via the tts() path
        tool_calling=True,
        structured_output=True,
        context_window=1_000_000 if ("1.5" in m or "2." in m) else 128_000,
        coding_suitability="high" if is_pro else "moderate",
    )


class Provider:
    """Abstract provider. A provider owns one credential + one ModelGateway."""
    name: str = "provider"

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    def capabilities(self, model: str | None = None) -> ModelCapabilities:  # pragma: no cover
        raise NotImplementedError

    async def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:  # pragma: no cover
        raise NotImplementedError


class GeminiProvider(Provider):
    """Gemini via ModelGateway. Used both for the built-in (zafven) key and for a
    user-supplied key — the only difference is which credential the gateway holds."""

    def __init__(self, gateway: ModelGateway, *, name: str, model: str) -> None:
        self.name = name
        self._gw = gateway
        self._model = model

    async def start(self) -> None:
        await self._gw.start()

    async def close(self) -> None:
        await self._gw.close()

    def capabilities(self, model: str | None = None) -> ModelCapabilities:
        caps = _gemini_caps(model or self._model)
        caps.provider = self.name
        return caps

    async def generate(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        kwargs.setdefault("model", self._model)
        return await self._gw.narrate(system_prompt, user_prompt, **kwargs)

    async def council(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        kwargs.setdefault("model", self._model)
        return await self._gw.council(system_prompt, user_prompt, **kwargs)


class CredentialVault:
    """Per-guild provider credentials, isolated from the rest of the system.

    Only `use()` (which builds a provider) and `masked()` (for a human) ever touch
    the raw key. `describe()` and everything else return provider/model + a mask.
    The key is never placed in a prompt, pattern, memory item, or log."""

    def __init__(self, store: object) -> None:
        self._store = store

    def _raw(self) -> dict:
        return dict(self._store.get(_NS_CREDS, {}) or {})  # type: ignore[attr-defined]

    def has_credential(self) -> bool:
        return bool(self._raw().get("key_b64"))

    async def set_credential(self, provider: str, key: str, model: str = "") -> None:
        # light obfuscation at rest — NOT encryption; documented as such.
        blob = base64.b64encode(key.strip().encode("utf-8")).decode("ascii")
        await self._store.set(_NS_CREDS, {  # type: ignore[attr-defined]
            "provider": (provider or "gemini").strip().lower(),
            "model": model.strip(),
            "key_b64": blob,
        })

    async def clear_credential(self) -> None:
        await self._store.set(_NS_CREDS, {})  # type: ignore[attr-defined]

    def describe(self) -> dict:
        """Safe metadata for UI: provider, model, masked key. Never the raw key."""
        raw = self._raw()
        return {
            "provider": raw.get("provider", ""),
            "model": raw.get("model", ""),
            "masked": self.masked(),
            "configured": bool(raw.get("key_b64")),
        }

    def masked(self) -> str:
        raw = self._raw()
        blob = raw.get("key_b64")
        if not blob:
            return ""
        try:
            key = base64.b64decode(blob).decode("utf-8")
        except Exception:  # noqa: BLE001
            return "••••"
        if len(key) <= 8:
            return "•" * len(key)
        return f"{key[:4]}…{key[-4:]}"

    def use(self) -> tuple[str, str, str] | None:
        """Return (provider, model, raw_key) for provider construction ONLY. This is
        the single method that yields the raw key, and its result must go straight
        into a provider, never into a prompt/log."""
        raw = self._raw()
        blob = raw.get("key_b64")
        if not blob:
            return None
        try:
            key = base64.b64decode(blob).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
        return raw.get("provider", "gemini"), raw.get("model", ""), key


class ProviderGateway:
    """Routes a call to the right provider for a guild and checks capabilities.

    Built-in provider wraps the bot's existing ModelGateway. If a guild has a stored
    credential and user keys are enabled, calls route to a per-guild provider built
    on that credential instead — with the intelligence layer unchanged (§20)."""

    def __init__(self, builtin: ModelGateway) -> None:
        self._builtin = GeminiProvider(builtin, name="zafven-builtin", model=config.GEMINI_MODEL)
        self._user_providers: dict[int, GeminiProvider] = {}

    def builtin(self) -> GeminiProvider:
        return self._builtin

    async def provider_for(self, guild_id: int, vault: CredentialVault | None) -> GeminiProvider:
        """Pick the provider for this guild: the user credential if enabled+present,
        else the built-in. A broken user credential falls back to built-in."""
        if not getattr(config, "PROVIDER_USER_KEYS_ENABLED", False) or vault is None:
            return self._builtin
        creds = vault.use()
        if not creds:
            return self._builtin
        provider, model, key = creds
        cached = self._user_providers.get(guild_id)
        if cached is not None:
            return cached
        try:
            gw = ModelGateway(api_key=key, model=model or config.GEMINI_MODEL)
            await gw.start()
        except Exception as exc:  # noqa: BLE001 — never leak the key in the error
            log.warning("user provider for guild %s failed to start; using built-in", guild_id)
            return self._builtin
        prov = GeminiProvider(gw, name=f"guild-{guild_id}-key", model=model or config.GEMINI_MODEL)
        self._user_providers[guild_id] = prov
        return prov

    def invalidate(self, guild_id: int) -> None:
        self._user_providers.pop(guild_id, None)

    @staticmethod
    def check_capability(caps: ModelCapabilities, needed: str) -> tuple[bool, str]:
        """Detect an unsupported capability rather than assuming it (§22)."""
        if caps.supports(needed):
            return True, ""
        return False, f"the selected model ({caps.provider}/{caps.model}) does not support {needed}"


__all__ = [
    "ModelCapabilities", "Provider", "GeminiProvider",
    "CredentialVault", "ProviderGateway", "GatewayError",
]
