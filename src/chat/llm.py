"""Provider-agnostic LLM interface. `AnthropicClient` is the concrete impl
used by default (assignment allows "any provider or model"); swapping
providers means writing one more class with the same `complete()` signature
-- nothing in answer.py or eval/ changes. Every call captures model name,
token counts, and an estimated cost, and (if given a Trace) records itself
as a span -- this is the LLM telemetry the observability requirement asks
for.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from src.config import CONFIG
from src.observability.tracing import Trace


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 1024,
                 trace: Optional[Trace] = None, span_name: str = "llm_call") -> LLMResponse:
        ...


class AnthropicClient(LLMClient):
    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        import anthropic
        self.model = model or CONFIG.llm_model
        key = api_key or CONFIG.anthropic_api_key
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add a real key."
            )
        self._client = anthropic.Anthropic(api_key=key)

    def complete(self, system: str, user: str, max_tokens: int = 1024,
                 trace: Optional[Trace] = None, span_name: str = "llm_call") -> LLMResponse:
        def _call():
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            in_tok = resp.usage.input_tokens
            out_tok = resp.usage.output_tokens
            cost = (in_tok / 1_000_000) * CONFIG.price_input_per_1m + \
                   (out_tok / 1_000_000) * CONFIG.price_output_per_1m
            return LLMResponse(text=text, model=self.model, input_tokens=in_tok,
                                output_tokens=out_tok, cost_usd=round(cost, 6))

        if trace is None:
            return _call()

        with trace.span(span_name, input={"system": system, "user": user}, model=self.model) as s:
            result = _call()
            s.output = {"text": result.text, "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens, "cost_usd": result.cost_usd}
            return result
