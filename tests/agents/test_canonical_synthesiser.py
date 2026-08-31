from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C11.RunManifest._1_0 import Pins

from agents.base import RunContext
from agents.canonical_synthesiser import (
    CanonicalSynthesiserAgent,
    _guardrail_g1_traces_to_cluster,
    _guardrail_g2_naming_convention,
    _work_item_for,
    make_canonical_synthesiser_factory,
)
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.validation import GuardrailViolation
from config.settings import ModelProvider, ModelTierConfig
from pipeline.run_store import RunStore
from tools.gateway import ToolGateway

RUN_ID = uuid4()


def _attr(local_name: str, region: str, *, obligation: str = "mandatory", tier: int = 1) -> C5Attributerecord:
    return C5Attributerecord.model_validate({
        "attributeId": f"attr://{region}/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": "string",
        "cardinality": "1..1",
        "obligation": {"level": obligation},
        "evidenceTier": tier,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x"],
    })


def _cluster(cluster_id: str, member_specs: list[tuple[str, str]]) -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": cluster_id,
        "members": [
            {"attributeId": aid, "region": region, "role": "core" if i == 0 else "variant", "pairScore": 1.0}
            for i, (aid, region) in enumerate(member_specs)
        ],
        "confidence": 0.9,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


class _FakeSubstrateApi:
    def __init__(self, run_store: RunStore) -> None:
        self._run_store = run_store

    def get_attribute(self, run_id: str, attribute_id: str) -> C5Attributerecord:
        for record in self._run_store.read_attributes(UUID(run_id)):
            if record.attributeId == attribute_id:
                return record
        raise KeyError(attribute_id)

    def search(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return []

    def acord_lookup(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return []


def _make_ctx(tmp_path: Path, *, provider: Any, seed_records: list[C5Attributerecord]) -> RunContext:
    run_store = RunStore(base_path=tmp_path / "run-store")
    by_region: dict[str, list[C5Attributerecord]] = {}
    for record in seed_records:
        by_region.setdefault(record.region.value, []).append(record)
    for region, records in by_region.items():
        run_store.write_attributes(RUN_ID, region, records)
    substrate = _FakeSubstrateApi(run_store)
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=RUN_ID)
    tier_config = {"high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")}
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={"canonical-synthesiser": "1.9.1"}, models={}, tools={}, algorithms={})
    return RunContext(run_id=RUN_ID, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)  # type: ignore[arg-type]


class _ScriptedProvider:
    def __init__(self, respond: Any) -> None:
        self._respond = respond

    def __call__(self, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        return ProviderResponse(text=self._respond(prompt), tokens_in=10, tokens_out=5)


def _candidate_json(
    *, cluster_id: str = "claim-id", placement: str = "core", placement_rule: str = "GUESS",
    obligation: str = "mandatory", data_type: str = "string", attribute: str = "claimId",
    entity: str = "Claim", cluster_refs: list[str] | None = None,
) -> str:
    return json.dumps({
        "candidateId": f"canon://Claim.{attribute}", "entity": entity, "attribute": attribute,
        "dataType": data_type, "cardinality": "1..1", "obligation": {"level": obligation},
        "placement": placement, "placementRule": placement_rule, "namingSource": "derived",
        "rationale": "x", "clusterRefs": cluster_refs if cluster_refs is not None else [f"cluster://{cluster_id}"],
        "weight": 5, "ratification": {"status": "pending", "sme": None, "decidedAt": None},
    })


class TestMakeCanonicalSynthesiserFactory:
    def test_placement_is_computed_by_code_not_the_model(self, tmp_path: Path) -> None:
        a = _attr("claimId", "us")
        b = _attr("claimId", "uk")
        c = _attr("claimId", "eu")
        provider = _ScriptedProvider(lambda p: _candidate_json(placement="extension:us", placement_rule="GUESS"))
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a, b, c])
        cluster = _cluster("claim-id", [(a.attributeId, "us"), (b.attributeId, "uk"), (c.attributeId, "eu")])

        synthesise = make_canonical_synthesiser_factory(ctx)
        candidate = synthesise(cluster, None, [])

        assert candidate is not None
        assert candidate.placement.value == "core"  # 3 regions -> Rule 1, not the model's guess
        assert candidate.placementRule == "1"

    def test_obligation_is_weakest_across_members(self, tmp_path: Path) -> None:
        a = _attr("x", "us", obligation="mandatory")
        b = _attr("x", "uk", obligation="optional")
        provider = _ScriptedProvider(lambda p: _candidate_json(cluster_id="x", obligation="mandatory", attribute="x"))
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a, b])
        cluster = _cluster("x", [(a.attributeId, "us"), (b.attributeId, "uk")])

        synthesise = make_canonical_synthesiser_factory(ctx)
        candidate = synthesise(cluster, None, [])

        assert candidate is not None
        assert candidate.obligation.level.value == "optional"

    def test_vendor_only_set_when_max_evidence_tier_is_3(self, tmp_path: Path) -> None:
        a = _attr("x", "us", tier=3)
        provider = _ScriptedProvider(lambda p: _candidate_json(cluster_id="x", attribute="x", placement="extension:us"))
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])

        synthesise = make_canonical_synthesiser_factory(ctx)
        candidate = synthesise(cluster, None, [])

        assert candidate is not None
        assert candidate.vendorOnly is True

    def test_vendor_only_false_for_normal_evidence(self, tmp_path: Path) -> None:
        a = _attr("x", "us", tier=1)
        provider = _ScriptedProvider(lambda p: _candidate_json(cluster_id="x", attribute="x", placement="extension:us"))
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])

        synthesise = make_canonical_synthesiser_factory(ctx)
        candidate = synthesise(cluster, None, [])

        assert candidate is not None
        assert candidate.vendorOnly is False

    def test_schema_failure_returns_none_not_an_exception(self, tmp_path: Path) -> None:
        a = _attr("x", "us")
        # Never a valid JSON object -> schema validation fails all 3 attempts.
        provider = _ScriptedProvider(lambda p: "{}")
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])

        synthesise = make_canonical_synthesiser_factory(ctx)
        candidate = synthesise(cluster, None, [])

        assert candidate is None


class TestGuardrailG1:
    def test_fires_when_cluster_refs_empty(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        violations = _guardrail_g1_traces_to_cluster({"clusterRefs": []}, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G1-missing-cluster-ref"

    def test_passes_when_cluster_refs_present(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        assert _guardrail_g1_traces_to_cluster({"clusterRefs": ["cluster://x"]}, ctx) == []


class TestGuardrailG2:
    def test_fires_for_bad_case(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        output = {"entity": "claim", "attribute": "LossDate", "placement": "core", "dataType": "string"}
        violations = _guardrail_g2_naming_convention(output, ctx)
        assert any(v.code == "G2-case" for v in violations)

    def test_passes_for_clean_name(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        output = {"entity": "Claim", "attribute": "lossDate", "placement": "core", "dataType": "date"}
        assert _guardrail_g2_naming_convention(output, ctx) == []

    def test_fires_for_region_marker_in_core_name(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        output = {"entity": "Claim", "attribute": "usLossDate", "placement": "core", "dataType": "date"}
        violations = _guardrail_g2_naming_convention(output, ctx)
        assert any(v.code == "G2-region-marker" for v in violations)


class TestValidateSemanticsDefensivePaths:
    def test_no_cluster_recorded_returns_no_violations(self, tmp_path: Path) -> None:
        # validate_semantics called without assemble_context having run
        # first (never happens via the real invoke() path, but is a real,
        # reachable state for any direct/misordered caller).
        agent = CanonicalSynthesiserAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[])
        assert agent.validate_semantics({"clusterRefs": []}, ctx) == []

    def test_cluster_ref_not_tracing_to_the_real_cluster_is_a_v2_violation(self, tmp_path: Path) -> None:
        a = _attr("x", "us")
        agent = CanonicalSynthesiserAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])
        item = _work_item_for(cluster, None, [], str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)

        # Well-formed enough to pass model_validate, but clusterRefs
        # names a cluster that isn't the one actually being synthesised
        # for - a genuine I3 tracing failure.
        output = json.loads(_candidate_json(cluster_id="does-not-exist", attribute="x"))
        violations = agent.validate_semantics(output, ctx)
        assert any(v.code.startswith("I3-") for v in violations)

    def test_malformed_mutated_output_is_handled_without_crashing(self, tmp_path: Path) -> None:
        a = _attr("x", "us")
        agent = CanonicalSynthesiserAgent()
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])
        item = _work_item_for(cluster, None, [], str(RUN_ID))
        agent.assemble_context(item, ctx.substrate)

        # Missing several fields C8Canonicalcandidate requires - forces
        # the model_validate(output) re-check inside validate_semantics
        # down its except-Exception path.
        output: dict[str, Any] = {"clusterRefs": ["cluster://x"], "obligation": {"level": "mandatory"}}
        violations = agent.validate_semantics(output, ctx)
        assert violations == []
        assert output["placement"] == "extension:us"


class TestInvokeIntegration:
    def test_bad_naming_escalates_via_guardrail(self, tmp_path: Path) -> None:
        a = _attr("x", "us")
        provider = _ScriptedProvider(lambda p: _candidate_json(cluster_id="x", attribute="LossDate", placement="extension:us"))
        ctx = _make_ctx(tmp_path, provider=provider, seed_records=[a])
        cluster = _cluster("x", [(a.attributeId, "us")])
        agent = CanonicalSynthesiserAgent()
        item = _work_item_for(cluster, None, [], str(RUN_ID))
        with pytest.raises(GuardrailViolation):
            agent.invoke(item, ctx)
