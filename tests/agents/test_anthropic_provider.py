"""
agents/model_gateway.py::anthropic_provider - the real Anthropic SDK
wiring. Most of the agent framework's own logic is tested against an
injectable fake provider (see test_model_gateway.py, test_base.py) -
this file specifically covers the real provider function: its fail-closed
behaviour hermetically (no key, no network call), and one genuine
end-to-end call under pytest.mark.llm (skips cleanly without a key,
same pattern as pytest.mark.db).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agents.model_gateway import Budget, ModelGateway, anthropic_provider
from config.settings import ModelProvider, ModelTierConfig

from llm_fixture import anthropic_key  # used as a pytest fixture below, not called directly


class TestAnthropicProviderFailsClosed:
    def test_no_key_anywhere_raises_before_any_network_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = anthropic_provider()
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            provider("claude-haiku-4-5-20251001", "hello", {}, 100)

    def test_constructing_the_provider_itself_never_requires_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        anthropic_provider()  # must not raise - the client is built lazily on first real call


class TestRealAnthropicCall:
    @pytest.mark.llm
    def test_a_real_call_returns_a_json_parsed_dict(self, anthropic_key: str) -> None:
        gateway = ModelGateway(tier_config={
            "fast": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="fast-v1", max_tokens=1024, model_id="claude-haiku-4-5-20251001"),
        })
        budget = Budget(total_tokens=100000, cost_ceiling=Decimal("10"), per_stage={}).slice_for("S1")
        schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
        prompt = (
            "Respond with exactly this JSON and nothing else, no markdown fences: "
            '{"ok": true}'
        )
        output = gateway.call("fast", prompt, response_schema=schema, budget=budget)
        assert output == {"ok": True}
