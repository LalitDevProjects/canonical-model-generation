from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from referencing import Registry, Resource

from generated.C11.RunManifest._1_0 import Pins

from agents.base import Agent, RunContext, WorkItem
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.prompt_render import REQUIRED_BLOCKS
from agents.validation import Guardrail, GuardrailViolation, Violation, WorkItemFailed
from config.settings import ModelProvider, ModelTierConfig
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from tools.gateway import ToolGateway

_TEMPLATE = "\n\n".join(
    f"[{name}]\n{name.lower()} block. {{{{item_id}}}} {{{{output_schema}}}}"
    for name in REQUIRED_BLOCKS
)

_SCHEMA = {
    "type": "object",
    "required": ["value"],
    "properties": {"value": {"type": "string"}},
    "additionalProperties": False,
}


def _write_template(tmp_path: Path) -> Path:
    directory = tmp_path / "fake-agent"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1.0.0.md").write_text(_TEMPLATE, encoding="utf-8")
    return tmp_path


class _ScriptedProvider:
    """Returns one ProviderResponse per call, from a fixed script -
    IndexError if invoked more times than scripted, which fails the test
    loudly rather than silently reusing the last response."""

    def __init__(self, script: list[str]) -> None:
        self._script = script
        self.calls: list[str] = []

    def __call__(self, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        self.calls.append(prompt)
        text = self._script[len(self.calls) - 1]
        return ProviderResponse(text=text, tokens_in=10, tokens_out=5)


def _make_ctx(tmp_path: Path, *, provider: Any, guardrails: list[Guardrail] | None = None) -> RunContext:
    run_id = uuid4()
    run_store = RunStore(base_path=tmp_path / "run-store")
    substrate = SubstrateApi(
        SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False,
    )
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=run_id)
    tier_config = {
        "fast": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="fast-v1", max_tokens=8000, model_id="claude-haiku-4-5-20251001"),
    }
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={}, models={}, tools={}, algorithms={})
    return RunContext(
        run_id=run_id, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway,
    )


class _FakeAgent(Agent):
    agent_id = "fake-agent"
    family = "discovery"
    output_schema = _SCHEMA
    prompt_template = "fake-agent"
    tools: list[str] = []
    model_tier = "fast"
    guardrails: list[Guardrail] = []

    def __init__(self, prompt_root: Path, *, semantic_violations: list[Violation] | None = None) -> None:
        self.prompt_root = prompt_root
        self._semantic_violations = semantic_violations or []

    def assemble_context(self, item: WorkItem, api: SubstrateApi) -> dict[str, Any]:
        return {"item_id": item.item_id}

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        return list(self._semantic_violations)


def _item() -> WorkItem:
    return WorkItem(item_id="item-1", stage="S1", kind="fake", payload={})


class TestInvokeHappyPath:
    def test_valid_first_attempt_returns_ok(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "hello"}'])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        result = agent.invoke(_item(), ctx)

        assert result.outcome == "ok"
        assert result.output == {"value": "hello"}
        assert len(provider.calls) == 1

    def test_writes_the_output_via_the_tool_gateway(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "hello"}'])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        agent.invoke(_item(), ctx)

        assert ctx.tools.written == [{"kind": "fake-agent", "payload": {"value": "hello"}}]

    def test_context_is_substituted_into_the_prompt(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "hello"}'])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        agent.invoke(_item(), ctx)

        assert "item-1" in provider.calls[0]


_EXTERNAL_DEFS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/agents-test-defs.json",
    "$defs": {"name": {"type": "string"}},
}
_SCHEMA_WITH_EXTERNAL_REF = {
    "type": "object",
    "required": ["value"],
    "properties": {"value": {"$ref": "https://example.invalid/agents-test-defs.json#/$defs/name"}},
    "additionalProperties": False,
}


class _FakeAgentWithExternalSchemaRef(_FakeAgent):
    """Increment 7: proves Agent.schema_registry is actually threaded
    through to validate_schema - output_schema here has an external $ref
    that only resolves if the registry is really used, the same shape
    Semantic Resolver's real contracts/C6/ConceptCluster/1.0.json needs."""

    output_schema = _SCHEMA_WITH_EXTERNAL_REF

    def __init__(self, prompt_root: Path, *, registry: Registry) -> None:
        super().__init__(prompt_root)
        self.schema_registry = registry


class TestSchemaRegistry:
    def test_default_agent_has_no_registry(self, tmp_path: Path) -> None:
        agent = _FakeAgent(tmp_path)
        assert agent.schema_registry is None

    def test_registry_is_used_to_resolve_an_external_ref_in_output_schema(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        registry = Registry().with_resource(
            "https://example.invalid/agents-test-defs.json", Resource.from_contents(_EXTERNAL_DEFS)
        )
        provider = _ScriptedProvider(['{"value": "hello"}'])
        agent = _FakeAgentWithExternalSchemaRef(root, registry=registry)
        ctx = _make_ctx(tmp_path, provider=provider)

        result = agent.invoke(_item(), ctx)

        assert result.outcome == "ok"
        assert result.output == {"value": "hello"}


class TestSchemaValidationRetry:
    def test_schema_violation_retries_twice_then_fails_the_work_item(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        # 3 attempts, all invalid (missing required "value") - 2 retries exhausted, 3rd fails.
        provider = _ScriptedProvider(["{}", "{}", "{}"])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(WorkItemFailed):
            agent.invoke(_item(), ctx)

        assert len(provider.calls) == 3

    def test_recovers_after_one_schema_retry(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(["{}", '{"value": "fixed"}'])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        result = agent.invoke(_item(), ctx)

        assert result.output == {"value": "fixed"}
        assert len(provider.calls) == 2

    def test_the_retry_prompt_includes_the_validation_error(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(["{}", '{"value": "fixed"}'])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        agent.invoke(_item(), ctx)

        assert "[CORRECTION]" in provider.calls[1]
        assert "failed schema validation" in provider.calls[1]

    def test_nothing_is_written_when_the_work_item_ultimately_fails(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(["{}", "{}", "{}"])
        agent = _FakeAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(WorkItemFailed):
            agent.invoke(_item(), ctx)

        assert ctx.tools.written == []


class TestSemanticValidationRetry:
    def test_semantic_violation_retries_once_then_escalates(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "a"}', '{"value": "b"}'])
        violation = Violation(level="V2", code="unresolvable-reference", detail="evref://x does not resolve")
        agent = _FakeAgent(root, semantic_violations=[violation])
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(WorkItemFailed) as exc_info:
            agent.invoke(_item(), ctx)

        assert len(provider.calls) == 2  # one retry, per the V2/V3 "retry once" policy
        assert exc_info.value.violations == [violation]

    def test_the_retry_prompt_names_the_offending_value(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "a"}', '{"value": "b"}'])
        violation = Violation(level="V2", code="unresolvable-reference", detail="evref://x does not resolve")
        agent = _FakeAgent(root, semantic_violations=[violation])
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(WorkItemFailed):
            agent.invoke(_item(), ctx)

        assert "unresolvable-reference" in provider.calls[1]


class TestGuardrailViolationNoRetry:
    def test_guardrail_violation_escalates_immediately_with_zero_retries(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "a"}'])
        violation = Violation(level="V4", code="G1", detail="guardrail failed")
        guardrail = Guardrail(id="G1", description="always fails", check=lambda output, ctx: [violation])

        class _GuardedAgent(_FakeAgent):
            guardrails = [guardrail]

        agent = _GuardedAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(GuardrailViolation) as exc_info:
            agent.invoke(_item(), ctx)

        assert len(provider.calls) == 1  # "no retry" - Section 7.6
        assert exc_info.value.violations == [violation]

    def test_nothing_is_written_on_a_guardrail_violation(self, tmp_path: Path) -> None:
        root = _write_template(tmp_path)
        provider = _ScriptedProvider(['{"value": "a"}'])
        violation = Violation(level="V4", code="G1", detail="guardrail failed")
        guardrail = Guardrail(id="G1", description="", check=lambda output, ctx: [violation])

        class _GuardedAgent(_FakeAgent):
            guardrails = [guardrail]

        agent = _GuardedAgent(root)
        ctx = _make_ctx(tmp_path, provider=provider)

        with pytest.raises(GuardrailViolation):
            agent.invoke(_item(), ctx)

        assert ctx.tools.written == []
