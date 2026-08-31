from __future__ import annotations

from decimal import Decimal

import pytest

from generated.C11.RunManifest._1_0 import Budget as ContractBudget

from agents.model_gateway import (
    Budget,
    BudgetExceeded,
    ModelGateway,
    ModelProviderError,
    ProviderResponse,
)
from config.settings import ModelProvider, ModelTierConfig


def _tier_config(model_id: str | None = "claude-haiku-4-5-20251001") -> dict[str, ModelTierConfig]:
    return {
        "fast": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="fast-v1", max_tokens=8000, model_id=model_id),
        "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id=model_id),
    }


class TestBudget:
    def test_check_passes_under_the_stage_cap(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={"S1": 0.5})
        budget.check("S1", 400)  # 400 <= 500 cap, no raise

    def test_check_raises_over_the_stage_cap(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={"S1": 0.5})
        with pytest.raises(BudgetExceeded):
            budget.check("S1", 600)  # 600 > 500 cap

    def test_unlisted_stage_defaults_to_the_full_total(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={"S1": 0.5})
        budget.check("S9", 999)  # no per_stage entry -> fraction 1.0 -> cap 1000

    def test_record_accumulates_spend_per_stage_independently(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={"S1": 0.5, "S2": 0.5})
        budget.record("S1", 300, Decimal("1"))
        budget.record("S2", 100, Decimal("1"))
        assert budget.spent_tokens == 400
        budget.check("S1", 199)  # 300+199=499 <= 500
        with pytest.raises(BudgetExceeded):
            budget.check("S1", 201)  # 300+201=501 > 500

    def test_cost_ceiling_exhausted_raises_even_under_token_cap(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("5"), per_stage={})
        budget.record("S1", 10, Decimal("5"))
        with pytest.raises(BudgetExceeded):
            budget.check("S1", 1)

    def test_from_contract_reuses_the_real_c11_runmanifest_budget_shape(self) -> None:
        contract_budget = ContractBudget.model_validate({
            "tokensTotal": 50000, "costCeilingGbp": 25.0, "perStage": {"S1": 0.2},
        })
        budget = Budget.from_contract(contract_budget)
        assert budget.total_tokens == 50000
        assert budget.cost_ceiling == Decimal("25.0")
        assert budget.per_stage == {"S1": 0.2}

    def test_slice_for_binds_a_stage(self) -> None:
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={"S1": 0.1})
        budget_slice = budget.slice_for("S1")
        with pytest.raises(BudgetExceeded):
            budget_slice.check(101)  # 101 > 100 cap
        budget_slice.record(50, Decimal("1"))
        assert budget.spent_tokens == 50


class TestModelGatewayCall:
    def test_n_a_tier_is_rejected(self) -> None:
        gateway = ModelGateway(tier_config=_tier_config())
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        with pytest.raises(ValueError, match="n/a"):
            gateway.call("n/a", "prompt", response_schema={}, budget=budget)

    def test_missing_model_id_for_tier_raises(self) -> None:
        gateway = ModelGateway(tier_config=_tier_config(model_id=None))
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        with pytest.raises(RuntimeError, match="model_id"):
            gateway.call("fast", "prompt", response_schema={}, budget=budget)

    def test_injected_provider_is_used_and_result_is_parsed_as_json(self) -> None:
        def fake_provider(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            return ProviderResponse(text='{"value": "ok"}', tokens_in=10, tokens_out=5)

        gateway = ModelGateway(tier_config=_tier_config(), provider=fake_provider)
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        output = gateway.call("fast", "prompt", response_schema={}, budget=budget)
        assert output == {"value": "ok"}

    def test_non_json_output_raises_schema_validation_failed(self) -> None:
        from agents.validation import SchemaValidationFailed

        def fake_provider(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            return ProviderResponse(text="not json at all", tokens_in=10, tokens_out=5)

        gateway = ModelGateway(tier_config=_tier_config(), provider=fake_provider)
        budget = Budget(total_tokens=1000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        with pytest.raises(SchemaValidationFailed):
            gateway.call("fast", "prompt", response_schema={}, budget=budget)

    def test_budget_is_checked_before_the_provider_is_called(self) -> None:
        calls: list[str] = []

        def fake_provider(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            calls.append("called")
            return ProviderResponse(text="{}", tokens_in=1, tokens_out=1)

        gateway = ModelGateway(tier_config=_tier_config(), provider=fake_provider)
        tiny_budget = Budget(total_tokens=1, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        with pytest.raises(BudgetExceeded):
            gateway.call("fast", "a very long prompt " * 100, response_schema={}, budget=tiny_budget)
        assert calls == []

    def test_budget_is_recorded_after_a_successful_call(self) -> None:
        def fake_provider(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            return ProviderResponse(text="{}", tokens_in=100, tokens_out=50)

        gateway = ModelGateway(tier_config=_tier_config(), provider=fake_provider)
        budget = Budget(total_tokens=10000, cost_ceiling=Decimal("100"), per_stage={})
        gateway.call("fast", "prompt", response_schema={}, budget=budget.slice_for("S1"))
        assert budget.spent_tokens == 150

    def test_provider_error_retries_up_to_the_configured_maximum_then_raises(self) -> None:
        attempts = {"n": 0}
        sleeps: list[float] = []

        def flaky_provider(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            attempts["n"] += 1
            raise ModelProviderError("503")

        gateway = ModelGateway(
            tier_config=_tier_config(), provider=flaky_provider,
            max_provider_retries=3, sleep_fn=sleeps.append,
        )
        budget = Budget(total_tokens=100000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        with pytest.raises(ModelProviderError):
            gateway.call("fast", "prompt", response_schema={}, budget=budget)
        assert attempts["n"] == 4  # initial attempt + 3 retries
        assert len(sleeps) == 3

    def test_provider_error_recovers_on_a_later_attempt(self) -> None:
        attempts = {"n": 0}

        def flaky_then_ok(model_id: str, prompt: str, response_schema: dict[str, object], max_tokens: int) -> ProviderResponse:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ModelProviderError("503")
            return ProviderResponse(text='{"value": "recovered"}', tokens_in=1, tokens_out=1)

        gateway = ModelGateway(
            tier_config=_tier_config(), provider=flaky_then_ok,
            max_provider_retries=5, sleep_fn=lambda _: None,
        )
        budget = Budget(total_tokens=100000, cost_ceiling=Decimal("100"), per_stage={}).slice_for("S1")
        output = gateway.call("fast", "prompt", response_schema={}, budget=budget)
        assert output == {"value": "recovered"}
        assert attempts["n"] == 3
