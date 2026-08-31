from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C11.RunManifest._1_0 import Pins

from agents.base import RunContext
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.semantic_resolver import (
    SemanticResolverAgent,
    _guardrail_g1_evidence_per_member,
    _guardrail_g2_cross_region_needs_confidence,
    _guardrail_g3_conflict_needs_alternative,
    _guardrail_g4_obligation_not_resolved_here,
    _guardrail_g5_low_confidence_needs_dissent,
    _work_item_for,
    make_semantic_resolver_adjudicator,
    resolve_escalation,
)
from agents.validation import GuardrailViolation, WorkItemFailed
from algorithms.clustering import ReviewPair
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import ModelProvider, ModelTierConfig
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from tools.gateway import ToolGateway

RUN_ID = uuid4()


def _attr(local_name: str, data_type: str, region: str = "us", **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://{region}/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _profiled(local_name: str, data_type: str, region: str = "us", **overrides: object) -> ProfiledAttribute:
    return profile(_attr(local_name, data_type, region, **overrides), siblings=[])


class _FakeSubstrateApi:
    """Real SubstrateApi.get_attribute() only ever reads via RunStore (no
    DB touched), so it's reused verbatim here; .search() is stubbed to an
    empty result rather than requiring a live Postgres - doc_chunks are
    supplementary LLM context, not decision-critical structure, so a
    hermetic test suite doesn't need a real hybrid-retrieval result to
    prove assemble_context/validate_semantics/guardrails/escalation."""

    def __init__(self, run_store: RunStore, *, search_results: list[Any] | None = None) -> None:
        self._run_store = run_store
        self._search_results = search_results or []

    def get_attribute(self, run_id: str, attribute_id: str) -> C5Attributerecord:
        for record in self._run_store.read_attributes(UUID(run_id)):
            if record.attributeId == attribute_id:
                return record
        raise KeyError(f"no attribute {attribute_id!r} found in run {run_id!r}")

    def search(self, run_id: str, query: str, **kwargs: object) -> list[Any]:
        return self._search_results


def _make_ctx(
    tmp_path: Path, *, provider: Any, seed_records: list[C5Attributerecord] | None = None, search_results: list[Any] | None = None,
) -> RunContext:
    run_store = RunStore(base_path=tmp_path / "run-store")
    if seed_records:
        by_region: dict[str, list[C5Attributerecord]] = {}
        for record in seed_records:
            by_region.setdefault(record.region.value, []).append(record)
        for region, records in by_region.items():
            run_store.write_attributes(RUN_ID, region, records)
    substrate = cast(SubstrateApi, _FakeSubstrateApi(run_store, search_results=search_results))
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=RUN_ID)
    tier_config = {"high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")}
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={"semantic-resolver": "2.3.0"}, models={}, tools={}, algorithms={})
    return RunContext(run_id=RUN_ID, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)


class _ScriptedProvider:
    def __init__(self, respond: Any) -> None:
        self._respond = respond

    def __call__(self, model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
        return ProviderResponse(text=self._respond(prompt), tokens_in=10, tokens_out=5)


def _valid_cluster_json(*, member_ids: list[str], regions: list[str], conflict_class: str | None = None, confidence: float = 0.9, dissent: str | None = None, alternatives: list[dict[str, str]] | None = None) -> str:
    payload: dict[str, Any] = {
        "clusterId": "cluster://cl-test0000000000",
        "proposedConcept": "lossDate",
        "members": [
            {"attributeId": aid, "region": region, "role": "core" if i == 0 else "variant", "pairScore": 0.9}
            for i, (aid, region) in enumerate(zip(member_ids, regions))
        ],
        "confidence": confidence,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x" for region in regions],
    }
    if conflict_class is not None:
        payload["conflictClass"] = conflict_class
    if dissent is not None:
        payload["dissent"] = dissent
    if alternatives is not None:
        payload["alternatives"] = alternatives
    return json.dumps(payload)


class TestWorkItemFor:
    def test_anchor_and_candidates_land_in_payload(self) -> None:
        anchor = _profiled("lossDate", "date")
        candidate = _profiled("dateOfLoss", "date", region="uk")
        item = _work_item_for(str(RUN_ID), anchor, [candidate])
        assert item.payload["anchor"]["attributeId"] == anchor.record.attributeId
        assert item.payload["candidates"][0]["attributeId"] == candidate.record.attributeId
        assert item.payload["run_id"] == str(RUN_ID)

    def test_item_id_is_deterministic(self) -> None:
        anchor = _profiled("lossDate", "date")
        candidate = _profiled("dateOfLoss", "date", region="uk")
        item1 = _work_item_for(str(RUN_ID), anchor, [candidate])
        item2 = _work_item_for(str(RUN_ID), anchor, [candidate])
        assert item1.item_id == item2.item_id


class TestAssembleContext:
    def test_returns_anchor_candidates_and_doc_chunks(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        candidate = _profiled("dateOfLoss", "date", region="uk")
        item = _work_item_for(str(RUN_ID), anchor, [candidate])
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))

        context = agent.assemble_context(item, ctx.substrate)

        assert context["anchor_record"]["attributeId"] == anchor.record.attributeId
        assert context["candidate_records"][0]["attributeId"] == candidate.record.attributeId
        assert context["doc_chunks"] == []

    def test_records_expected_attribute_ids_for_later_semantics_check(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        candidate = _profiled("dateOfLoss", "date", region="uk")
        item = _work_item_for(str(RUN_ID), anchor, [candidate])
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))

        agent.assemble_context(item, ctx.substrate)

        assert agent._expected_attribute_ids == frozenset({anchor.record.attributeId, candidate.record.attributeId})

    def test_doc_chunks_are_assembled_from_search_results(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        item = _work_item_for(str(RUN_ID), anchor, [])

        class _Chunk:
            evref = "evref://us/git/art-1@1234567890abcdef#/x"
            text = "Date the loss occurred."

        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), search_results=[_Chunk()])

        context = agent.assemble_context(item, ctx.substrate)

        assert context["doc_chunks"] == [{"evref": _Chunk.evref, "text": _Chunk.text}]


class TestValidateSemantics:
    def test_invented_member_is_a_violation(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        item = _work_item_for(str(RUN_ID), anchor, [])
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        agent.assemble_context(item, ctx.substrate)

        output = {"members": [{"attributeId": "attr://us/art-1/Claim.notSupplied"}], "evidenceRefs": []}
        violations = agent.validate_semantics(output, ctx)
        assert any(v.code == "invented-member" for v in violations)

    def test_member_drawn_from_supplied_set_is_not_invented(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        item = _work_item_for(str(RUN_ID), anchor, [])
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        agent.assemble_context(item, ctx.substrate)

        output = {"members": [{"attributeId": anchor.record.attributeId}], "evidenceRefs": [str(anchor.record.evidenceRefs[0])]}
        violations = agent.validate_semantics(output, ctx)
        assert not any(v.code == "invented-member" for v in violations)

    def test_unresolvable_evidence_ref_is_a_v2_violation(self, tmp_path: Path) -> None:
        agent = SemanticResolverAgent()
        anchor = _profiled("lossDate", "date")
        item = _work_item_for(str(RUN_ID), anchor, [])
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        agent.assemble_context(item, ctx.substrate)

        output = {"members": [], "evidenceRefs": ["evref://us/git/some-other-artefact@1234567890abcdef#/x"]}
        violations = agent.validate_semantics(output, ctx)
        assert any(v.code == "unresolvable-reference" for v in violations)


class TestGuardrails:
    def test_g1_passes_when_member_evidence_overlaps_cluster_evidence(self, tmp_path: Path) -> None:
        anchor = _attr("lossDate", "date")
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[anchor])
        output = {"members": [{"attributeId": anchor.attributeId}], "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"]}
        assert _guardrail_g1_evidence_per_member(output, ctx) == []

    def test_g1_fails_when_member_has_no_overlapping_evidence(self, tmp_path: Path) -> None:
        anchor = _attr("lossDate", "date")
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[anchor])
        output = {"members": [{"attributeId": anchor.attributeId}], "evidenceRefs": ["evref://us/git/other@1234567890abcdef#/x"]}
        violations = _guardrail_g1_evidence_per_member(output, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G1-no-evidence"

    def test_g1_fails_when_member_is_unresolvable(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"members": [{"attributeId": "attr://us/art-1/Claim.missing"}], "evidenceRefs": []}
        violations = _guardrail_g1_evidence_per_member(output, ctx)
        assert violations[0].code == "G1-unresolvable-member"

    def test_g2_fires_for_cross_region_clean_merge_with_low_confidence(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"members": [{"region": "us"}, {"region": "uk"}], "conflictClass": None, "confidence": 0.5}
        violations = _guardrail_g2_cross_region_needs_confidence(output, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G2-low-confidence-cross-region"

    def test_g2_passes_for_cross_region_with_high_confidence(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"members": [{"region": "us"}, {"region": "uk"}], "conflictClass": None, "confidence": 0.9}
        assert _guardrail_g2_cross_region_needs_confidence(output, ctx) == []

    def test_g2_passes_for_single_region(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"members": [{"region": "us"}], "conflictClass": None, "confidence": 0.1}
        assert _guardrail_g2_cross_region_needs_confidence(output, ctx) == []

    def test_g3_fires_when_conflict_class_set_but_no_alternatives(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"conflictClass": "type", "alternatives": []}
        violations = _guardrail_g3_conflict_needs_alternative(output, ctx)
        assert any(v.code == "G3-missing-alternative" for v in violations)

    def test_g3_fires_for_whitespace_only_why_rejected(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"conflictClass": "type", "alternatives": [{"description": "x", "whyRejected": "   "}]}
        violations = _guardrail_g3_conflict_needs_alternative(output, ctx)
        assert any(v.code == "G3-empty-why-rejected" for v in violations)

    def test_g3_passes_with_a_real_alternative(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        output = {"conflictClass": "type", "alternatives": [{"description": "x", "whyRejected": "types diverge"}]}
        assert _guardrail_g3_conflict_needs_alternative(output, ctx) == []

    def test_g3_not_applicable_when_no_conflict(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g3_conflict_needs_alternative({"conflictClass": None}, ctx) == []

    def test_g4_fires_when_obligation_claimed_but_levels_match(self, tmp_path: Path) -> None:
        a = _attr("x", "string", obligation={"level": "mandatory"})
        b = _attr("x", "string", region="uk", obligation={"level": "mandatory"})
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[a, b])
        output = {"conflictClass": "obligation", "members": [{"attributeId": a.attributeId}, {"attributeId": b.attributeId}]}
        violations = _guardrail_g4_obligation_not_resolved_here(output, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G4-false-obligation-conflict"

    def test_g4_passes_when_obligation_genuinely_differs(self, tmp_path: Path) -> None:
        a = _attr("x", "string", obligation={"level": "mandatory"})
        b = _attr("x", "string", region="uk", obligation={"level": "optional"})
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[a, b])
        output = {"conflictClass": "obligation", "members": [{"attributeId": a.attributeId}, {"attributeId": b.attributeId}]}
        assert _guardrail_g4_obligation_not_resolved_here(output, ctx) == []

    def test_g4_skips_unresolvable_members_when_checking_obligation_levels(self, tmp_path: Path) -> None:
        a = _attr("x", "string", obligation={"level": "mandatory"})
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"), seed_records=[a])
        output = {
            "conflictClass": "obligation",
            "members": [{"attributeId": a.attributeId}, {"attributeId": "attr://us/art-1/Claim.missing"}],
        }
        # Only one member resolves (levels={"mandatory"}) - still "not
        # genuinely differing", so this still fires, but via the
        # unresolvable-member skip path, not a crash.
        violations = _guardrail_g4_obligation_not_resolved_here(output, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G4-false-obligation-conflict"

    def test_g4_not_applicable_when_no_obligation_conflict_claimed(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g4_obligation_not_resolved_here({"conflictClass": "type"}, ctx) == []

    def test_g5_fires_for_low_confidence_without_dissent(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        violations = _guardrail_g5_low_confidence_needs_dissent({"confidence": 0.5}, ctx)
        assert len(violations) == 1
        assert violations[0].code == "G5-missing-dissent"

    def test_g5_passes_with_dissent_populated(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g5_low_confidence_needs_dissent({"confidence": 0.5, "dissent": "uncertain about UK member"}, ctx) == []

    def test_g5_not_applicable_for_high_confidence(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        assert _guardrail_g5_low_confidence_needs_dissent({"confidence": 0.95}, ctx) == []


class TestResolveEscalation:
    def test_homonym_escalates(self) -> None:
        escalate, reason = resolve_escalation({"conflictClass": "homonym", "confidence": 0.9})
        assert escalate is True
        assert "homonym" in reason

    def test_low_confidence_escalates(self) -> None:
        escalate, reason = resolve_escalation({"conflictClass": None, "confidence": 0.4})
        assert escalate is True
        assert "confidence" in reason

    def test_confident_clean_merge_does_not_escalate(self) -> None:
        escalate, _ = resolve_escalation({"conflictClass": None, "confidence": 0.9})
        assert escalate is False


class TestMakeSemanticResolverAdjudicator:
    def test_empty_review_pairs_yields_nothing(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(lambda p: "{}"))
        adjudicate = make_semantic_resolver_adjudicator(ctx, run_store=RunStore(base_path=tmp_path / "run-store"))
        assert list(adjudicate([])) == []

    def test_yields_a_real_cluster_for_a_review_pair(self, tmp_path: Path) -> None:
        a = _profiled("lossDate", "date")
        b = _profiled("dateOfLoss", "date", region="uk")
        run_store = RunStore(base_path=tmp_path / "run-store")

        def respond(prompt: str) -> str:
            return _valid_cluster_json(member_ids=[a.record.attributeId, b.record.attributeId], regions=["us", "uk"], confidence=0.9)

        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(respond), seed_records=[a.record, b.record])
        adjudicate = make_semantic_resolver_adjudicator(ctx, run_store=run_store)

        pairs = [ReviewPair(a=a, b=b, score=0.6, features={})]
        clusters = list(adjudicate(pairs))

        assert len(clusters) == 1
        assert {m.attributeId for m in clusters[0].members} == {a.record.attributeId, b.record.attributeId}

    def test_homonym_escalation_is_persisted_to_triage(self, tmp_path: Path) -> None:
        a = _profiled("claimDate", "dateTime", region="uk")
        b = _profiled("claimDate", "string", region="eu")
        run_store = RunStore(base_path=tmp_path / "run-store")

        def respond(prompt: str) -> str:
            return _valid_cluster_json(
                member_ids=[a.record.attributeId], regions=["uk"], conflict_class="homonym", confidence=0.9,
                alternatives=[{"description": "merge with EU claimDate", "whyRejected": "type-incompatible"}],
            )

        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(respond), seed_records=[a.record, b.record])
        adjudicate = make_semantic_resolver_adjudicator(ctx, run_store=run_store)

        pairs = [ReviewPair(a=a, b=b, score=0.6, features={})]
        list(adjudicate(pairs))

        entries = run_store.read_triage_entries(RUN_ID)
        assert len(entries) == 1
        assert entries[0].kind == "agent-escalation"
        assert "homonym" in entries[0].reason

    def test_a_guardrail_violation_escalates_via_the_agent_runtime(self, tmp_path: Path) -> None:
        # conflictClass set but no alternatives - G3 fires, and G3 gets 0
        # retries (Section 7.6) so this raises immediately.
        a = _profiled("lossDate", "date")
        b = _profiled("dateOfLoss", "date", region="uk")

        def respond(prompt: str) -> str:
            return _valid_cluster_json(
                member_ids=[a.record.attributeId, b.record.attributeId], regions=["us", "uk"],
                conflict_class="type", confidence=0.9, alternatives=[],
            )

        ctx = _make_ctx(tmp_path, provider=_ScriptedProvider(respond), seed_records=[a.record, b.record])
        adjudicate = make_semantic_resolver_adjudicator(ctx, run_store=RunStore(base_path=tmp_path / "run-store"))

        pairs = [ReviewPair(a=a, b=b, score=0.6, features={})]
        with pytest.raises(GuardrailViolation):
            list(adjudicate(pairs))
