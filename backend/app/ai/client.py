"""LLM client behind a small interface.

Every AI job asks for JSON that matches a schema (structured outputs), so callers get
validated data, never free-form code. :class:`AnthropicLLM` is the production client;
:class:`DisabledLLM` is used when no credentials are configured, and tests plug in a
fake. Swap providers by adding another class with the same ``complete_json`` method.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Literal, Protocol

from app.config import get_settings

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high"]

# Server-side refusal fallback (re-runs a declined request on another model inside the
# same call). Supported on these model families; Haiku has no server-side fallback.
_FALLBACK_PREFIXES = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """The LLM call failed or returned something unusable. Callers fall back."""


class LLMUnavailableError(LLMError):
    """No LLM is configured."""


class LLMClient(Protocol):
    """Minimal interface every provider implements."""

    @property
    def available(self) -> bool: ...

    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: Effort = "low",
        max_tokens: int = 4000,
    ) -> dict[str, Any]: ...


class DisabledLLM:
    """Stand-in when AI is not configured: every call raises LLMUnavailableError."""

    available = False
    model = "none"

    def complete_json(self, **_: Any) -> dict[str, Any]:
        """Always unavailable."""
        raise LLMUnavailableError("AI features are not configured (set ANTHROPIC_API_KEY).")


class AnthropicLLM:
    """Claude via the official Anthropic SDK, with structured JSON output."""

    available = True

    def __init__(
        self, model: str, api_key: str | None = None, timeout: float = 60.0, client: Any = None
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self._model = model
        # A bare constructor resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an
        # `ant auth login` profile; pass the key only when settings provide one.
        kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 2}
        if api_key:
            kwargs["api_key"] = api_key
        self._client = client or anthropic.Anthropic(**kwargs)

    @property
    def model(self) -> str:
        """Model id in use."""
        return self._model

    def request_params(
        self, *, system: str, user: str, schema: dict[str, Any], effort: Effort, max_tokens: int
    ) -> dict[str, Any]:
        """The exact Messages API parameters for one call (exposed for tests)."""
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if self._model.startswith(_FALLBACK_PREFIXES):
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def agent_turn(
        self,
        *,
        task: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        schema: dict[str, Any],
        effort: Effort,
        tools_enabled: bool = True,
        timeout: float = 60.0,
        max_tokens: int = 8000,
    ) -> Any:
        """One step of an agent loop; returns the raw Messages API response."""
        params: dict[str, Any] = {
            **self.request_params(
                system=system, user="", schema=schema, effort=effort, max_tokens=max_tokens
            ),
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "auto" if tools_enabled else "none"},
            "cache_control": {"type": "ephemeral"},
        }
        client = self._client.with_options(timeout=timeout)
        a = self._anthropic
        try:
            if "betas" in params:
                response = client.beta.messages.create(**params)
            else:
                response = client.messages.create(**params)
        except a.RateLimitError as exc:
            raise LLMError("The AI service is busy; please try again shortly.") from exc
        except a.APIStatusError as exc:
            log.warning("LLM %s failed: HTTP %s %s", task, exc.status_code, exc.message)
            raise LLMError("The AI service returned an error.") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service.") from exc
        log.info("LLM %s stop=%s usage=%s", task, response.stop_reason, response.usage)
        return response

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: Effort = "low",
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Call Claude and return the schema-valid JSON object it produced."""
        params = self.request_params(
            system=system, user=user, schema=schema, effort=effort, max_tokens=max_tokens
        )
        a = self._anthropic
        try:
            if "betas" in params:
                response = self._client.beta.messages.create(**params)
            else:
                response = self._client.messages.create(**params)
        except a.RateLimitError as exc:
            raise LLMError("The AI service is busy; please try again shortly.") from exc
        except a.APIStatusError as exc:
            log.warning("LLM %s failed: HTTP %s %s", task, exc.status_code, exc.message)
            raise LLMError("The AI service returned an error.") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Could not reach the AI service.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("The AI declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The AI response was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise LLMError("The AI returned no answer.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("The AI returned malformed JSON.") from exc
        log.info(
            "LLM %s ok (model=%s, in=%s, out=%s)",
            task,
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return data


def ai_enabled() -> bool:
    """AI is on when explicitly enabled, or automatically when an API key is set."""
    s = get_settings()
    return s.llm_enabled if s.llm_enabled is not None else bool(s.anthropic_api_key)


@lru_cache
def _configured_llm() -> LLMClient:
    s = get_settings()
    if not ai_enabled():
        return DisabledLLM()
    return AnthropicLLM(
        s.llm_model, api_key=s.anthropic_api_key or None, timeout=s.llm_timeout_seconds
    )


_override: LLMClient | None = None


def set_llm_override(llm: LLMClient | None) -> None:
    """Use ``llm`` everywhere (API and background jobs) - for tests and scripts."""
    global _override
    _override = llm


def get_llm() -> LLMClient:
    """The LLM client in use (FastAPI dependency and background tasks)."""
    return _override if _override is not None else _configured_llm()
