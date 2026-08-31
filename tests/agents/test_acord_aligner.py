from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C11.RunManifest._1_0 import Pins

from agents.acord_aligner import (
    AcordAlignerAgent,
    DEGRADED_MODE_RATIONALE,
    _guardrail_g2_partial_requires_deviation,
    _guardrail_g3_no_forced_fit,
    _work_item_for,
    align_or_degrade,
    degraded_alignment,
)
from agents.base import RunContext
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.validation import GuardrailViolation, WorkItemFailed
from config.settings import ModelProvider, ModelTierConfig
from pipeline.run_store import RunStore
from tools.gateway import ToolGateway

RUN_ID = uuid4()


def _cluster(cluster_id: str = "loss-date", *, concept: str = "lossDate") -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": concept,
        "members": [{"attributeId": "attr://us/art-1/Claim.x", "region": "us", "role": "core", "pairScore": 1.0}],
        "confidence": 0.9,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


class _FakeAcordConcept:
    def __init__(self, acord_ref: str, entity: str = "Claim", attribute: str | None = "lossDate") -> None:
        self.acord_ref = acord_ref
        self.model = "data"
        self.entity = entity
        self.attribute = attribute


class _FakeSubstrateApi:
    def __init__(self, run_store: RunStore, *, acord_results: list[_FakeAcordConcept] | None = None) -> None:
        self._run_store = run_store
        self._acord_results = acord_results or []

    def acord_lookup(self, run_id: str, query: str, *, top_k: int = 10) -> list[Any]:
        return self._acord_results

    def search(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return []


def _make_ctx(tmp_path: Path, *, provider: Any, acord_results: list[_FakeAcordConcept] | None = None) -> RunContext:
    run_store = RunStore(base_path=tmp_path / "run-store")
    substrate = _FakeSubstrateApi(run_store, acord_results=acord_results)
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=RUN_ID)
    tier_config = {"high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")}
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={"acord-aligner": "1.6.0"}, models={}, tools={}, algorithms={})
    return RunContext(run_id=RUN_ID, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)  # type: ignore[arg-type]


class _ScriptedProvider:
    def __init__(self, respond: Any) -> None:
        self._respond = respond

    def __call__(self, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        return ProviderResponse(text=self._respond(prompt), tokens_in=10, tokens_out=5)


def _misfit_json() -> str:
    return json.dumps({
        "clusterId": "cluster://loss-date", "acordRef": None, "verdict": "misfit",
        "deviation": None, "rationale": "No reasonable ACORD counterpart.",
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


def _fit_json(acord_ref: str) -> str:
    return json.dumps({
        "clusterId": "cluster://loss-date", "acordRef": acord_ref, "verdict": "fit",
        "deviation": None, "rationale": "Matches ACORD Claim.lossDate exactly.",
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


class TestDegradedAlignment:
    def test_produces_unassessed_verdict(self) -> None:
        record = degraded_alignment(_cluster())
        assert record["verdict"] == "unassessed"
        assert record["acordRef"] is None
        assert record["deviation"] is None
        assert record["rationale"] == DEGRADED_MODE_RATIONALE

    def test_reuses_cluster_evidence_refs(self) -> None:
        record = degraded_alignment(_cluster())
        assert record["evidenceRefs"] == ["evref://us/git/art-1@1234567890abcdef#/x"]

    def test_validates_against_the_real_schema(self) -> None:
        from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord
        C7Alignmentrecord.model_validate(degraded_alignment(_cluster()))


class TestAlignOrDegrade:
    def test_unpermitted_licence_never_invokes_the_agent(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: (_ for _ in ()).throw(AssertionError("model should never be called")))
        ctx = _make_ctx(tmp_path, provider=provider)
        records = list(align_or_degrade([_cluster()], ctx, licence_disposition="unpermitted"))
        assert len(records) == 1
        assert records[0].verdict.value == "unassessed"

    def test_permitted_licence_invokes_the_real_agent(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _misfit_json())
        ctx = _make_ctx(tmp_path, provider=provider)
        records = list(align_or_degrade([_cluster()], ctx, licence_disposition="permitted"))
        assert len(records) == 1
        assert records[0].verdict.value == "misfit"

    def test_multiple_clusters_each_get_their_own_record(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _misfit_json())
        ctx = _make_ctx(tmp_path, provider=provider)
        clusters = [_cluster("a"), _cluster("b")]
        # Both scripted responses reuse the same clusterId text - only the
        # count and per-call independence matters here.
        records = list(align_or_degrade(clusters, ctx, licence_disposition="unpermitted"))
        assert len(records) == 2


class TestAssembleContext:
    def test_calls_acord_lookup_and_records_returned_refs(self, tmp_path: Path) -> None:
        agent = AcordAlignerAgent()
        concept = _FakeAcordConcept("claim/lossDate")
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), acord_results=[concept])
        item = _work_item_for(_cluster(), str(RUN_ID))

        context = agent.assemble_context(item, ctx.substrate)

        assert context["acord_results"][0]["acordRef"] == "acord://claim/lossDate"
        assert agent._returned_acord_refs == frozenset({"acord://claim/lossDate"})

    def test_no_results_leaves_empty_returned_refs(self, tmp_path: Path) -> None:
        agent = AcordAlignerAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), acord_results=[])
        item = _work_item_for(_cluster(), str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)
        assert agent._returned_acord_refs == frozenset()


class TestValidateSemanticsG1:
    def test_fit_with_cited_ref_is_valid(self, tmp_path: Path) -> None:
        agent = AcordAlignerAgent()
        concept = _FakeAcordConcept("claim/lossDate")
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), acord_results=[concept])
        item = _work_item_for(_cluster(), str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)

        violations = agent.validate_semantics({"verdict": "fit", "acordRef": "acord://claim/lossDate"}, ctx)
        assert violations == []

    def test_fit_with_uncited_ref_is_a_violation(self, tmp_path: Path) -> None:
        agent = AcordAlignerAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), acord_results=[])
        item = _work_item_for(_cluster(), str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)

        violations = agent.validate_semantics({"verdict": "fit", "acordRef": "acord://invented"}, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G1-uncited-acord-reference"

    def test_misfit_needs_no_ref_check(self, tmp_path: Path) -> None:
        agent = AcordAlignerAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        item = _work_item_for(_cluster(), str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)
        assert agent.validate_semantics({"verdict": "misfit", "acordRef": None}, ctx) == []


class TestGuardrails:
    def test_g2_fires_for_partial_with_no_deviation(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        violations = _guardrail_g2_partial_requires_deviation({"verdict": "partial", "deviation": None}, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G2-missing-deviation"

    def test_g2_passes_with_a_real_deviation(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g2_partial_requires_deviation({"verdict": "partial", "deviation": "narrower usage"}, ctx) == []

    def test_g2_not_applicable_to_other_verdicts(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g2_partial_requires_deviation({"verdict": "fit", "deviation": None}, ctx) == []

    def test_g3_fires_when_deviation_echoes_misfit_language(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"verdict": "partial", "deviation": "No reasonable ACORD counterpart really."}
        violations = _guardrail_g3_no_forced_fit(output, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G3-forced-fit"

    def test_g3_passes_for_a_genuine_deviation(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"verdict": "partial", "deviation": "syndicate usage is narrower, excludes reserve amounts"}
        assert _guardrail_g3_no_forced_fit(output, ctx) == []


class TestInvokeIntegration:
    def test_partial_with_blank_deviation_escalates_via_guardrail(self, tmp_path: Path) -> None:
        # "" (not null) so this passes the schema's own if/then conditional
        # (verdict=partial -> deviation: {"type": "string"}, which null
        # would already fail at V1) and genuinely reaches G2's own check.
        provider = _ScriptedProvider(lambda p: json.dumps({
            "clusterId": "cluster://loss-date", "acordRef": "acord://claim/lossDate", "verdict": "partial",
            "deviation": "   ", "rationale": "x", "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
        }))
        concept = _FakeAcordConcept("claim/lossDate")
        ctx = _make_ctx(tmp_path, provider=provider, acord_results=[concept])
        with pytest.raises(GuardrailViolation):
            list(align_or_degrade([_cluster()], ctx, licence_disposition="permitted"))

    def test_fit_with_invented_ref_fails_after_retry(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(lambda p: _fit_json("acord://invented"))
        ctx = _make_ctx(tmp_path, provider=provider, acord_results=[])
        with pytest.raises(WorkItemFailed):
            list(align_or_degrade([_cluster()], ctx, licence_disposition="permitted"))
