"""Optional AI narrative: explanation and summarisation only, never decisions.

A tiny provider-agnostic :class:`LLMClient` protocol with Anthropic and OpenAI implementations over
``httpx``. Every call is logged with token counts and charged against a monthly budget in the state
store. The model never sees keys, account identifiers, or raw trade logs beyond aggregates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from kestrel.config import LLMConfig, Secrets
from kestrel.logsetup import get_logger

log = get_logger(__name__)

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class LLMResponse:
    """Text plus token accounting."""

    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


class LLMClient(Protocol):
    """One method: complete a prompt."""

    provider: str
    model: str

    def complete(self, system: str, prompt: str, *, max_tokens: int) -> LLMResponse:
        """Return the model's text."""
        ...


class AnthropicClient:
    """Messages API over httpx."""

    provider = "anthropic"

    def __init__(self, api_key: str, model: str | None = None, *, http: httpx.Client | None = None) -> None:
        """Create a client; ``http`` can be injected for tests."""
        self._key = api_key
        self.model = model or ANTHROPIC_DEFAULT_MODEL
        self._http = http or httpx.Client(timeout=60)

    def complete(self, system: str, prompt: str, *, max_tokens: int) -> LLMResponse:
        """Call ``/v1/messages``."""
        r = self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": self.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return LLMResponse(text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), self.provider, self.model)


class OpenAIClient:
    """Chat completions over httpx."""

    provider = "openai"

    def __init__(self, api_key: str, model: str | None = None, *, http: httpx.Client | None = None) -> None:
        """Create a client; ``http`` can be injected for tests."""
        self._key = api_key
        self.model = model or OPENAI_DEFAULT_MODEL
        self._http = http or httpx.Client(timeout=60)

    def complete(self, system: str, prompt: str, *, max_tokens: int) -> LLMResponse:
        """Call ``/v1/chat/completions``."""
        r = self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
            json={"model": self.model, "max_tokens": max_tokens, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)), self.provider, self.model)


class UsageStore(Protocol):
    """What the budget needs from the state store."""

    def add_llm_usage(self, ts: datetime, provider: str, model: str, input_tokens: int, output_tokens: int, purpose: str) -> None:
        """Record a call."""
        ...

    def llm_tokens_since(self, since: datetime) -> int:
        """Tokens used since ``since``."""
        ...


def build_client(cfg: LLMConfig, secrets: Secrets) -> LLMClient | None:
    """Return a client when enabled and a key exists; otherwise ``None`` (feature absent)."""
    if not cfg.enabled:
        return None
    anthropic = secrets.anthropic_api_key.get_secret_value() if secrets.has("anthropic_api_key") and secrets.anthropic_api_key else None
    openai = secrets.openai_api_key.get_secret_value() if secrets.has("openai_api_key") and secrets.openai_api_key else None
    if cfg.provider in ("auto", "anthropic") and anthropic:
        return AnthropicClient(anthropic, cfg.model)
    if cfg.provider in ("auto", "openai") and openai:
        return OpenAIClient(openai, cfg.model)
    return None


class Narrator:
    """Budgeted, logged, degrade-gracefully wrapper around a client."""

    SYSTEM = (
        "You write short, plain-language narratives around numbers computed by a paper-trading research bot. "
        "State what moved, which positions drove PnL, and which warnings fired. Never recommend trades, never give "
        "financial advice, never invent numbers. Australian English. Under 150 words."
    )

    def __init__(self, client: LLMClient | None, cfg: LLMConfig, store: UsageStore | None, *, now: Any = None) -> None:
        """Create a narrator; ``client`` may be ``None`` (every call returns ``None``)."""
        self.client = client
        self.cfg = cfg
        self.store = store
        self._now = now or (lambda: datetime.now(tz=UTC))
        self.warned_budget = False

    @property
    def available(self) -> bool:
        """Whether narratives can be produced at all."""
        return self.client is not None

    def tokens_this_month(self) -> int:
        """Tokens used since the first of the month."""
        if self.store is None:
            return 0
        now = self._now()
        return int(self.store.llm_tokens_since(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))

    def narrate(self, purpose: str, payload: dict[str, Any]) -> str | None:
        """Produce prose for ``payload`` (aggregates only). ``None`` when absent, over budget, or failed."""
        if self.client is None:
            return None
        used = self.tokens_this_month()
        if used >= self.cfg.monthly_token_budget:
            if not self.warned_budget:
                log.warning("llm_budget_exhausted", used=used, budget=self.cfg.monthly_token_budget)
                self.warned_budget = True
            return None
        prompt = "Metrics JSON:\n" + json.dumps(payload, indent=2, sort_keys=True, default=str)
        try:
            resp = self.client.complete(self.SYSTEM, prompt, max_tokens=self.cfg.max_output_tokens)
        except Exception as exc:  # noqa: BLE001 - provider failure degrades to the non-AI report
            log.warning("llm_provider_failed", error=str(exc))
            return None
        if self.store is not None:
            self.store.add_llm_usage(self._now(), resp.provider, resp.model, resp.input_tokens, resp.output_tokens, purpose)
        log.info("llm_call", purpose=purpose, input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)
        return resp.text.strip()
