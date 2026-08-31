from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from generated.C11.RunManifest._1_0 import Pins

from agents.base import RunContext
from agents.mapping_generator import (
    MappingGeneratorAgent,
    _guardrail_g2_closed_transform_vocabulary,
    _guardrail_g3_weight_5_forbids_silent_failure,
    _guardrail_g4_lossy_transform_requires_note,
    _guardrail_g5_evidence_cited,
    _work_item_for,
    make_mapping_generator_factory,
)
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.validation import GuardrailViolation, WorkItemFailed
from config.settings import ModelProvider, ModelTierConfig
from pipeline.run_store import RunStore
from tools.gateway import ToolGateway

RUN_ID = uuid4()
_EVREF = f"evref://uk/git/art-1@{'a' * 16}#/x"


class _FakeSubstrateApi:
    def get_attribute(self, run_id: str, attribute_id: str) -> Any:
        raise KeyError(attribute_id)

    def search(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return []

    def acord_lookup(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return []


def _make_ctx(tmp_path: Path, *, provider: Any) -> RunContext:
    run_store = RunStore(base_path=tmp_path / "run-store")
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=RUN_ID)
    tier_config = {"high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")}
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={"mapping-generator": "1.4.0"}, models={}, tools={}, algorithms={})
    return RunContext(run_id=RUN_ID, substrate=_FakeSubstrateApi(), pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)  # type: ignore[arg-type]


class _ScriptedProvider:
    def __init__(self, respond: Any) -> None:
        self._respond = respond

    def __call__(self, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        return ProviderResponse(text=self._respond(prompt), tokens_in=10, tokens_out=5)


def _region_records(*paths: str) -> list[dict[str, Any]]:
    return [{"path": p} for p in paths]


def _spec_json(*, mappings: list[dict[str, Any]]) -> str:
    return json.dumps({
        "header": {
            "mappingSpecId": "mapping-fixture",
            "canonicalRef": "canon://claims/1.0",
            "direction": "toCanonical",
            "generatedFrom": {"run": str(RUN_ID), "corpusManifest": "corpusmanifest-x", "agent": "mapping-generator/1.4.0"},
        },
        "mappings": mappings,
    })


def _entry(*, canonical: str = "c", region: str = "x", transform: str = "identity", weight: int = 1,
           on_failure: str = "escalate", note: str | None = None, evidence: list[str] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "canonical": canonical, "region": region, "transform": transform,
        "weight": weight, "onFailure": on_failure,
        "evidence": evidence if evidence is not None else [_EVREF],
    }
    if note is not None:
        entry["note"] = note
    return entry


class TestMakeMappingGeneratorFactory:
    def test_valid_spec_round_trips_through_invoke(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _spec_json(mappings=[_entry()]))
        ctx = _make_ctx(tmp_path, provider=provider)
        generate = make_mapping_generator_factory(ctx)

        spec = generate(_region_records("x"), {}, {}, "mapping-fixture")

        assert spec.header.mappingSpecId == "mapping-fixture"
        assert len(spec.mappings) == 1

    def test_unparseable_output_raises_work_item_failed(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: "{}")
        ctx = _make_ctx(tmp_path, provider=provider)
        generate = make_mapping_generator_factory(ctx)

        with pytest.raises(WorkItemFailed):
            generate(_region_records("x"), {}, {}, "mapping-fixture")


class TestGuardrailG2ClosedVocabulary:
    def test_fires_for_unknown_transform(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="notARealTransform")]}
        violations = _guardrail_g2_closed_transform_vocabulary(output, ctx)
        assert any(v.code == "G2-unknown-transform" for v in violations)

    def test_fires_for_unparseable_transform_string(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="not a valid call (")]}
        violations = _guardrail_g2_closed_transform_vocabulary(output, ctx)
        assert any(v.code == "G2-unparseable-transform" for v in violations)

    def test_passes_for_known_transform(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="identity")]}
        assert _guardrail_g2_closed_transform_vocabulary(output, ctx) == []

    def test_disposition_entry_with_no_transform_is_ignored(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [{"canonical": None, "disposition": {"status": "unmapped", "reason": "x"}}]}
        assert _guardrail_g2_closed_transform_vocabulary(output, ctx) == []


class TestGuardrailG3WeightRule:
    def test_fires_for_weight_5_with_skip(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(weight=5, on_failure="skip")]}
        violations = _guardrail_g3_weight_5_forbids_silent_failure(output, ctx)
        assert any(v.code == "G3-weight-5-silent-failure" for v in violations)

    def test_fires_for_weight_5_with_default(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(weight=5, on_failure="default")]}
        violations = _guardrail_g3_weight_5_forbids_silent_failure(output, ctx)
        assert any(v.code == "G3-weight-5-silent-failure" for v in violations)

    def test_passes_for_weight_5_with_reject(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(weight=5, on_failure="reject")]}
        assert _guardrail_g3_weight_5_forbids_silent_failure(output, ctx) == []

    def test_passes_for_low_weight_with_skip(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(weight=1, on_failure="skip")]}
        assert _guardrail_g3_weight_5_forbids_silent_failure(output, ctx) == []


class TestGuardrailG4LossyRequiresNote:
    def test_fires_for_lossy_transform_without_note(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="normaliseCase(mode='upper')", note=None)]}
        violations = _guardrail_g4_lossy_transform_requires_note(output, ctx)
        assert any(v.code == "G4-undeclared-lossy-transform" for v in violations)

    def test_passes_for_lossy_transform_with_note(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="normaliseCase(mode='upper')", note="declared loss")]}
        assert _guardrail_g4_lossy_transform_requires_note(output, ctx) == []

    def test_passes_for_non_lossy_transform_without_note(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="identity", note=None)]}
        assert _guardrail_g4_lossy_transform_requires_note(output, ctx) == []

    def test_unparseable_transform_is_skipped_not_double_flagged(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry(transform="not a valid call (", note=None)]}
        assert _guardrail_g4_lossy_transform_requires_note(output, ctx) == []

    def test_disposition_entry_with_no_transform_is_ignored(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [{"canonical": None, "disposition": {"status": "unmapped", "reason": "x"}}]}
        assert _guardrail_g4_lossy_transform_requires_note(output, ctx) == []


class TestGuardrailG5EvidenceCited:
    def test_fires_when_evidence_missing(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [{"canonical": "c", "evidence": []}]}
        violations = _guardrail_g5_evidence_cited(output, ctx)
        assert any(v.code == "G5-missing-evidence" for v in violations)

    def test_passes_when_evidence_present(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"mappings": [_entry()]}
        assert _guardrail_g5_evidence_cited(output, ctx) == []


class TestValidateSemanticsG1Totality:
    def test_fires_for_uncovered_region_attribute(self, tmp_path: Path) -> None:
        agent = MappingGeneratorAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        item = _work_item_for(_region_records("x", "y"), {}, {}, "mapping-fixture")
        agent.assemble_context(item, ctx.substrate)

        output = {"mappings": [_entry(region="x")]}
        violations = agent.validate_semantics(output, ctx)
        assert any(v.code == "G1-totality" and v.record_id == "y" for v in violations)

    def test_passes_when_every_attribute_covered(self, tmp_path: Path) -> None:
        agent = MappingGeneratorAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        item = _work_item_for(_region_records("x"), {}, {}, "mapping-fixture")
        agent.assemble_context(item, ctx.substrate)

        output = {"mappings": [_entry(region="x")]}
        assert agent.validate_semantics(output, ctx) == []

    def test_no_context_assembled_yet_returns_no_violations(self, tmp_path: Path) -> None:
        agent = MappingGeneratorAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert agent.validate_semantics({"mappings": []}, ctx) == []


class TestInvokeIntegration:
    def test_uncovered_attribute_escalates_via_semantic_retry_then_fails(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _spec_json(mappings=[_entry(region="x")]))
        ctx = _make_ctx(tmp_path, provider=provider)
        agent = MappingGeneratorAgent()
        item = _work_item_for(_region_records("x", "y"), {}, {}, "mapping-fixture")
        with pytest.raises(WorkItemFailed):
            agent.invoke(item, ctx)

    def test_unknown_transform_escalates_via_guardrail(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _spec_json(mappings=[_entry(transform="notARealTransform")]))
        ctx = _make_ctx(tmp_path, provider=provider)
        agent = MappingGeneratorAgent()
        item = _work_item_for(_region_records("x"), {}, {}, "mapping-fixture")
        with pytest.raises(GuardrailViolation):
            agent.invoke(item, ctx)
