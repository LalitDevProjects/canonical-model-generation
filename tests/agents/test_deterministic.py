from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from generated.C11.RunManifest._1_0 import Pins

import pytest

from agents.base import RunContext, WorkItem
from agents.deterministic import DeterministicAgent
from agents.model_gateway import Budget, ModelGateway
from agents.validation import Guardrail, GuardrailViolation, Violation, WorkItemFailed
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from tools.gateway import ToolGateway

_SCHEMA = {"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}}


def _make_ctx(tmp_path: Path) -> RunContext:
    run_id = uuid4()
    run_store = RunStore(base_path=tmp_path / "run-store")
    substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=run_id)
    model_gateway = ModelGateway(tier_config={})
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={}, models={}, tools={}, algorithms={})
    return RunContext(run_id=run_id, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)


class _FakeDeterministicAgent(DeterministicAgent):
    agent_id = "fake-deterministic"
    family = "comprehension"
    output_schema = _SCHEMA
    prompt_template = ""
    tools: list[str] = []
    guardrails: list[Guardrail] = []

    def __init__(self, *, raw: dict[str, Any], semantic_violations: list[Violation] | None = None) -> None:
        self._raw = raw
        self._semantic_violations = semantic_violations or []

    def compute(self, item: WorkItem, ctx: RunContext) -> dict[str, Any]:
        return self._raw

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        return list(self._semantic_violations)


def _item() -> WorkItem:
    return WorkItem(item_id="item-1", stage="S2", kind="fake", payload={})


class TestAssembleContextIsTrivial:
    def test_returns_an_empty_dict(self, tmp_path: Path) -> None:
        agent = _FakeDeterministicAgent(raw={"value": "x"})
        assert agent.assemble_context(_item(), api=None) == {}  # type: ignore[arg-type]


class TestInvokeHappyPath:
    def test_valid_output_returns_ok(self, tmp_path: Path) -> None:
        agent = _FakeDeterministicAgent(raw={"value": "hello"})
        ctx = _make_ctx(tmp_path)
        result = agent.invoke(_item(), ctx)
        assert result.outcome == "ok"
        assert result.output == {"value": "hello"}

    def test_no_retry_no_model_gateway_involvement(self, tmp_path: Path) -> None:
        # ModelGateway has no provider configured at all - if invoke()
        # ever tried to call it, this would raise before reaching here.
        agent = _FakeDeterministicAgent(raw={"value": "hello"})
        ctx = _make_ctx(tmp_path)
        agent.invoke(_item(), ctx)  # must not touch ctx.model_gateway


class TestInvokeSchemaFailure:
    def test_schema_invalid_output_fails_the_work_item_immediately_no_retry(self, tmp_path: Path) -> None:
        agent = _FakeDeterministicAgent(raw={})  # missing required "value"
        ctx = _make_ctx(tmp_path)
        with pytest.raises(WorkItemFailed, match="schema-invalid"):
            agent.invoke(_item(), ctx)


class TestInvokeSemanticFailure:
    def test_semantic_violation_fails_the_work_item_immediately_no_retry(self, tmp_path: Path) -> None:
        violation = Violation(level="V2", code="unresolvable-reference", detail="bad ref")
        agent = _FakeDeterministicAgent(raw={"value": "x"}, semantic_violations=[violation])
        ctx = _make_ctx(tmp_path)
        with pytest.raises(WorkItemFailed) as exc_info:
            agent.invoke(_item(), ctx)
        assert exc_info.value.violations == [violation]


class TestInvokeGuardrailFailure:
    def test_guardrail_violation_raises_and_writes_nothing(self, tmp_path: Path) -> None:
        violation = Violation(level="V4", code="G1", detail="failed")
        guardrail = Guardrail(id="G1", description="", check=lambda output, ctx: [violation])

        class _GuardedAgent(_FakeDeterministicAgent):
            guardrails = [guardrail]

        agent = _GuardedAgent(raw={"value": "x"})
        ctx = _make_ctx(tmp_path)
        with pytest.raises(GuardrailViolation) as exc_info:
            agent.invoke(_item(), ctx)
        assert exc_info.value.violations == [violation]
        assert ctx.tools.written == []
