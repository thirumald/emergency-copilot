"""Optional LLM providers. OFF by default: nothing is sent anywhere unless the operator configures it.

    COPILOT_LLM=off | anthropic | openai_compat
    COPILOT_LLM_MODEL            default claude-opus-5-5 (anthropic)
    COPILOT_LLM_SEND_CALL_DATA=1 separate opt-in before any call transcript / case data may be sent to the LLM
    ANTHROPIC_API_KEY            anthropic provider (read by the SDK)
    COPILOT_LLM_BASE_URL / COPILOT_LLM_API_KEY / COPILOT_LLM_MODEL   openai_compat provider (any OpenAI-compatible server,
                                 for example a self-hosted vLLM, so data can stay on premise)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = "claude-opus-5-5"


class LLMError(Exception):
    pass


@dataclass
class LLMConfig:
    provider: str = "off"
    model: str = DEFAULT_MODEL
    send_call_data: bool = False
    base_url: str = ""
    max_tokens: int = 4096
    reason: str = ""  # why a requested provider is unavailable
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        prov = os.environ.get("COPILOT_LLM", "off").lower()
        cfg = cls(provider=prov if prov in ("anthropic", "openai_compat") else "off",
                  model=os.environ.get("COPILOT_LLM_MODEL", DEFAULT_MODEL),
                  send_call_data=os.environ.get("COPILOT_LLM_SEND_CALL_DATA") == "1",
                  base_url=os.environ.get("COPILOT_LLM_BASE_URL", "").rstrip("/"))
        if prov not in ("off", "anthropic", "openai_compat"):
            cfg.reason = f"unknown COPILOT_LLM value '{prov}'"
        return cfg


class AnthropicLLM:
    """Claude via the official SDK. Supports tool use (needed by the support agent)."""

    supports_tools = True

    def __init__(self, cfg: LLMConfig, client: Any = None):
        self.cfg = cfg
        if client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover
                raise LLMError("the 'anthropic' package is not installed (pip install anthropic)") from e
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise LLMError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic()
        self.client = client

    def create(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> Any:
        kwargs: dict[str, Any] = dict(model=self.cfg.model, max_tokens=self.cfg.max_tokens, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools
        # server-side refusal fallback (default-on for this model family); beta endpoint, same response shape
        return self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)

    def complete_text(self, system: str, user: str) -> str:
        resp = self.create(system, [{"role": "user", "content": user}])
        if resp.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


class OpenAICompatLLM:
    """Any OpenAI-compatible chat endpoint (for example self-hosted vLLM). Text only; no tool use."""

    supports_tools = False

    def __init__(self, cfg: LLMConfig):
        if not cfg.base_url:
            raise LLMError("COPILOT_LLM_BASE_URL is not set")
        self.cfg = cfg

    def complete_text(self, system: str, user: str) -> str:
        import httpx

        headers = {"Authorization": f"Bearer {os.environ['COPILOT_LLM_API_KEY']}"} if os.environ.get("COPILOT_LLM_API_KEY") else {}
        r = httpx.post(f"{self.cfg.base_url}/chat/completions", headers=headers, timeout=30.0, json={
            "model": self.cfg.model, "max_tokens": self.cfg.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise LLMError(f"provider returned HTTP {r.status_code}")
        return r.json()["choices"][0]["message"]["content"].strip()


def build_llm(cfg: LLMConfig) -> AnthropicLLM | OpenAICompatLLM | None:
    """Return a provider, or None (and set cfg.reason) so the app keeps working without AI."""
    if cfg.provider == "off":
        return None
    try:
        return AnthropicLLM(cfg) if cfg.provider == "anthropic" else OpenAICompatLLM(cfg)
    except LLMError as e:
        cfg.reason = str(e)
        return None
