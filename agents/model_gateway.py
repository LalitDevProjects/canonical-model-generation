"""
The model gateway (Section 7.6-7.7): budget enforcement and the real
provider call. Structured output is NOT assumed provider-enforced - the
prompt's own [OUTPUT] block inlines the response schema as instruction
text, and agents/validation.py::validate_schema (real jsonschema
validation) is the actual enforcement, matching the spec's own
pseudocode where `validate_schema(raw, ...)` is a distinct step after
the model call, with V1 retry on failure.

Confirmed decision (this session): a real Anthropic provider, not a
continued mock - `anthropic_provider()` makes real API calls. The
underlying call is injectable (`ProviderFn`), the same dependency-
injection style gate/gate.py::classify_and_redact and
substrate/ingest.py::ingest_artefacts already use, so the agent
framework's own retry/escalation/budget logic is testable with a
scripted fake, never a real network call.
"""

from __future__ import annotations

import json
import os
import random
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import anthropic

from generated.C11.RunManifest._1_0 import Budget as ContractBudget

from agents.validation import SchemaValidationFailed
from config.settings import ModelTierConfig

_PLACEHOLDER_COST_PER_1K_TOKENS = Decimal("0.001")
"""NOT real Anthropic pricing - a PoC placeholder so Budget.cost_ceiling
enforcement has something to enforce against, same honesty standard as
config/settings.py's own StorageConfig.postgres_dsn placeholder. Real
per-model pricing changes over time and belongs in config, not a
hardcoded constant, if this ever needs to be accurate."""


class BudgetExceeded(Exception):
    def __init__(self, scope: str, cap: object) -> None:
        super().__init__(f"budget exceeded for {scope!r} (cap={cap!r})")
        self.scope = scope
        self.cap = cap


class ModelProviderError(Exception):
    """5xx / throttle - retried by ModelGateway.call, distinct from the
    schema/semantic retry budget in Agent.invoke()."""


@dataclass(frozen=True)
class BudgetSlice:
    """Section 7.1's `ctx.budget.slice_for(self.agent_id)` - resolved
    here against `WorkItem.stage` rather than the agent id: the work
    item already carries which stage it belongs to (Section 8.2), so
    nothing needs a second, separately-maintained agent-to-stage map."""

    budget: "Budget"
    stage: str

    def check(self, estimated_tokens: int) -> None:
        self.budget.check(self.stage, estimated_tokens)

    def record(self, tokens: int, cost: Decimal) -> None:
        self.budget.record(self.stage, tokens, cost)


class Budget:
    """Transcribed from Section 7.6's own pseudocode, with one real bug
    fixed: the spec's `check()` reads `self.stage_spend[stage]` but
    `__init__` never assigns it - a `defaultdict(int)` here is what that
    line evidently intended. "Enforced by model-gateway on every call. A
    run cannot exceed its ceiling." """

    def __init__(self, total_tokens: int, cost_ceiling: Decimal, per_stage: dict[str, float]) -> None:
        self.total_tokens = total_tokens
        self.cost_ceiling = cost_ceiling
        self.per_stage = per_stage
        self.spent_tokens = 0
        self.spent_cost = Decimal(0)
        self._spent_by_stage: dict[str, int] = defaultdict(int)

    @classmethod
    def from_contract(cls, contract_budget: ContractBudget) -> "Budget":
        """Constructed FROM the already-real generated.C11.RunManifest.Budget
        field, not a new config section - Section 7.6's own Budget class
        and C11 RunManifest's budget field describe the same thing."""
        return cls(
            total_tokens=contract_budget.tokensTotal,
            cost_ceiling=Decimal(str(contract_budget.costCeilingGbp)),
            per_stage=dict(contract_budget.perStage),
        )

    def check(self, stage: str, estimated_tokens: int) -> None:
        cap = int(self.total_tokens * self.per_stage.get(stage, 1.0))
        if self._spent_by_stage[stage] + estimated_tokens > cap:
            raise BudgetExceeded(stage, cap)
        if self.spent_cost >= self.cost_ceiling:
            raise BudgetExceeded("run", self.cost_ceiling)

    def record(self, stage: str, tokens: int, cost: Decimal) -> None:
        self._spent_by_stage[stage] += tokens
        self.spent_tokens += tokens
        self.spent_cost += cost

    def slice_for(self, stage: str) -> BudgetSlice:
        return BudgetSlice(budget=self, stage=stage)


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    tokens_in: int
    tokens_out: int


ProviderFn = Callable[[str, str, dict[str, Any], int], ProviderResponse]
"""(model_id, prompt, response_schema, max_tokens) -> ProviderResponse."""


def anthropic_provider(api_key: str | None = None) -> ProviderFn:
    """Real Anthropic SDK wiring. The client is built lazily on first
    real call, never at import time or at anthropic_provider() call
    time, so importing this module - or constructing a ModelGateway with
    an injected fake provider for tests - never requires a key.
    Structured output is requested via the prompt's own [OUTPUT] block
    (see agents/prompt_render.py), not a provider-side schema constraint
    - this repo's own validate_schema step is the real enforcement."""
    _client: list[anthropic.Anthropic] = []

    def _get_client() -> anthropic.Anthropic:
        if not _client:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set - see README for how to get an Anthropic API key"
                )
            _client.append(anthropic.Anthropic(api_key=key))
        return _client[0]

    def _call(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        client = _get_client()
        try:
            message = client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(f"ANTHROPIC_API_KEY was rejected: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise ModelProviderError(str(exc)) from exc

        text = "".join(block.text for block in message.content if block.type == "text")
        return ProviderResponse(
            text=text,
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
        )

    return _call


def _estimate_tokens(prompt: str) -> int:
    """A rough, documented approximation (chars/4) - not a real
    tokenizer. Used only for the pre-call budget check
    (Budget.check(estimated_tokens)); the real spend recorded afterwards
    comes from the provider's own reported usage."""
    return max(1, len(prompt) // 4)


@dataclass
class ModelGateway:
    tier_config: dict[str, ModelTierConfig]
    provider: ProviderFn | None = None
    max_provider_retries: int = 5
    sleep_fn: Callable[[float], None] = field(default=time.sleep)
    """Injectable so tests exercise the real retry-count logic without
    really sleeping - a scripted no-op sleep_fn, same spirit as the
    injectable provider itself."""

    def _resolved_provider(self) -> ProviderFn:
        return self.provider or anthropic_provider()

    def call(
        self,
        tier: str,
        prompt: str,
        *,
        response_schema: dict[str, Any],
        budget: BudgetSlice,
    ) -> dict[str, Any]:
        if tier == "n/a":
            raise ValueError("model_tier 'n/a' agents are deterministic and must not call the model gateway")
        config = self.tier_config[tier]
        if config.model_id is None:
            raise RuntimeError(f"tier {tier!r} (tier_id={config.tier_id!r}) has no model_id configured")

        estimated_tokens = _estimate_tokens(prompt)
        budget.check(estimated_tokens)

        provider = self._resolved_provider()
        response = self._call_with_retry(provider, config.model_id, prompt, response_schema, config.max_tokens)

        cost = Decimal(response.tokens_in + response.tokens_out) / 1000 * _PLACEHOLDER_COST_PER_1K_TOKENS
        budget.record(response.tokens_in + response.tokens_out, cost)

        try:
            parsed: dict[str, Any] = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise SchemaValidationFailed(f"model output was not valid JSON: {exc}") from exc
        return parsed

    def _call_with_retry(
        self, provider: ProviderFn, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int,
    ) -> ProviderResponse:
        attempt = 0
        while True:
            try:
                return provider(model_id, prompt, response_schema, max_tokens)
            except ModelProviderError:
                if attempt >= self.max_provider_retries:
                    raise
                backoff = (2**attempt) + random.uniform(0, 1)
                self.sleep_fn(backoff)
                attempt += 1
