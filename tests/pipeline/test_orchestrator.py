"""
Hermetic tests for pipeline/orchestrator.py::create_run/resume_after_checkpoint -
the driving orchestrator behind Section 12's run-control API. Runs
entirely against real golden/git/claims-{us,uk,eu}/ fixtures through the
real connectors -> gate -> parsers -> algorithms.clustering path (zero
LLM, zero DB), mirroring how tests/connectors/test_golden_corpus_e2e.py
and tests/algorithms/test_clustering_acceptance.py already prove each
piece individually - this test wires them together for real, end to end,
exactly as pipeline/orchestrator.py::create_run() itself does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from generated.C11.RunManifest._1_0 import C11Runmanifest

from agents.model_gateway import ModelGateway, ProviderResponse
from config.settings import ModelProvider, ModelTierConfig, load_settings
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from pipeline.orchestrator import (
    CheckpointNotCompleteError,
    CheckpointNotSealedError,
    CorpusDriftDetected,
    UnsupportedDomainError,
    create_run,
    resume_after_checkpoint,
)
from pipeline.run_store import RunStore

pytestmark = pytest.mark.e2e

_CLUSTER_ID_PATTERN = re.compile(r'"clusterId":\s*"(cluster://[^"]+)"')
_PROPOSED_CONCEPT_PATTERN = re.compile(r'"proposedConcept":\s*"([^"]+)"')


def _scripted_synthesiser_response(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
    """A real ProviderFn (agents/model_gateway.py's own injectable
    interface) - not a live network call, but a genuine schema-valid
    response built from the real cluster JSON the prompt actually
    carries (proving the continuation's own wiring end to end, the same
    _ScriptedProvider pattern every agent's own hermetic test in this
    repo already uses)."""
    cluster_match = _CLUSTER_ID_PATTERN.search(prompt)
    concept_match = _PROPOSED_CONCEPT_PATTERN.search(prompt)
    cluster_id = cluster_match.group(1) if cluster_match else "cluster://unknown"
    attribute = concept_match.group(1) if concept_match else "x"
    text = json.dumps({
        "candidateId": f"canon://Claim.{attribute}", "entity": "Claim", "attribute": attribute,
        "dataType": "string", "cardinality": "1..1", "obligation": {"level": "mandatory"},
        "placement": "core", "placementRule": "1", "namingSource": "derived", "rationale": "test candidate",
        "clusterRefs": [cluster_id], "weight": 5,
        "ratification": {"status": "pending", "sme": None, "decidedAt": None},
    })
    return ProviderResponse(text=text, tokens_in=10, tokens_out=10)


def _scripted_model_gateway() -> ModelGateway:
    tier_config = {
        "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")
    }
    return ModelGateway(tier_config=tier_config, provider=_scripted_synthesiser_response)


def _stores(tmp_path: Path) -> tuple[RunStore, EvidenceStore, LedgerStore]:
    return (
        RunStore(base_path=tmp_path / "run-store"),
        EvidenceStore(base_path=tmp_path / "evidence-store"),
        LedgerStore(base_path=tmp_path / "ledger-store"),
    )


def _create(tmp_path: Path) -> tuple[RunStore, C11Runmanifest]:
    run_store, evidence_store, ledger_store = _stores(tmp_path)
    settings = load_settings()
    manifest = create_run(
        domain="claims",
        trigger={"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
        pins=None, parameters=None, budget=None, previous_run_id=None,
        settings=settings, run_store=run_store, evidence_store=evidence_store, ledger_store=ledger_store,
    )
    return run_store, manifest


class TestCreateRunHermeticEndToEnd:
    def test_unsupported_domain_raises(self, tmp_path: Path) -> None:
        run_store, evidence_store, ledger_store = _stores(tmp_path)
        with pytest.raises(UnsupportedDomainError):
            create_run(
                domain="policy",
                trigger={"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
                pins=None, parameters=None, budget=None, previous_run_id=None,
                settings=load_settings(), run_store=run_store, evidence_store=evidence_store, ledger_store=ledger_store,
            )

    def test_run_ends_at_await_triage(self, tmp_path: Path) -> None:
        _, manifest = _create(tmp_path)
        assert manifest.state == "AWAIT_TRIAGE"

    def test_corpus_hash_is_real_and_non_placeholder(self, tmp_path: Path) -> None:
        _, manifest = _create(tmp_path)
        assert manifest.corpusHash != "0" * 64
        assert len(manifest.corpusHash) == 64

    def test_run_manifest_is_durably_persisted(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        reread = run_store.read_run_manifest(manifest.runId)
        assert reread == manifest

    def test_all_three_regions_admitted_at_least_one_artefact(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        corpus = run_store.read_corpus_manifest(manifest.runId)
        assert {a.region.value for a in corpus.artefacts} == {"us", "uk", "eu"}

    def test_attributes_are_persisted_per_region(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        for region in ("us", "uk", "eu"):
            assert run_store.read_attributes(manifest.runId, region), f"no attributes persisted for {region}"

    def test_real_clusters_are_persisted_and_cross_region(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        clusters = run_store.read_clusters(manifest.runId)
        assert clusters, "expected at least one real cluster"
        regions_seen = {member.region.value for cluster in clusters for member in cluster.members}
        assert regions_seen == {"us", "uk", "eu"}

    def test_triage_checkpoint_is_sealed_with_the_real_corpus_hash(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        sealed = run_store.read_sealed_checkpoint(manifest.runId, "TRIAGE")
        assert sealed is not None
        assert sealed["corpusHashAtSeal"] == manifest.corpusHash
        assert sealed["checkpoint"] == "TRIAGE"

    def test_journal_records_every_real_stage_in_order(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        stages = [e.stage for e in run_store.read_journal_events(manifest.runId)]
        assert stages == ["S1", "S3", "S4", "S4"]

    def test_two_independent_runs_produce_the_same_corpus_hash(self, tmp_path: Path) -> None:
        run_store1, evidence_store1, ledger_store1 = _stores(tmp_path / "run1")
        run_store2, evidence_store2, ledger_store2 = _stores(tmp_path / "run2")
        settings = load_settings()
        trigger = {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"}
        m1 = create_run(domain="claims", trigger=trigger, pins=None, parameters=None, budget=None, previous_run_id=None,
                         settings=settings, run_store=run_store1, evidence_store=evidence_store1, ledger_store=ledger_store1)
        m2 = create_run(domain="claims", trigger=trigger, pins=None, parameters=None, budget=None, previous_run_id=None,
                         settings=settings, run_store=run_store2, evidence_store=evidence_store2, ledger_store=ledger_store2)
        assert m1.corpusHash == m2.corpusHash
        assert m1.runId != m2.runId


class TestResumeAfterCheckpointHermeticPaths:
    def test_unsealed_checkpoint_raises(self, tmp_path: Path) -> None:
        run_store, _, _ = _stores(tmp_path)
        with pytest.raises(CheckpointNotSealedError):
            resume_after_checkpoint(
                run_id=uuid4(), checkpoint="TRIAGE", run_store=run_store, settings=load_settings(), model_gateway=None,
            )

    def test_incomplete_decisions_raises(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        with pytest.raises(CheckpointNotCompleteError):
            resume_after_checkpoint(
                run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store, settings=load_settings(), model_gateway=None,
            )

    def test_corpus_drift_since_seal_raises(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)
        drifted = run_store.read_run_manifest(manifest.runId).model_copy(update={"corpusHash": "f" * 64})
        run_store.write_run_manifest(manifest.runId, drifted)
        with pytest.raises(CorpusDriftDetected):
            resume_after_checkpoint(
                run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store, settings=load_settings(), model_gateway=None,
            )

    def test_no_model_provider_transitions_to_await_model_provider(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)
        result = resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store, settings=load_settings(), model_gateway=None,
        )
        assert result.state == "AWAIT_MODEL_PROVIDER"

    def test_no_model_provider_journals_an_honest_escalation(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)
        resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store, settings=load_settings(), model_gateway=None,
        )
        events = run_store.read_journal_events(manifest.runId)
        last_event = events[-1]
        assert last_event.stage == "TRIAGE"
        assert last_event.outcome is not None
        assert last_event.outcome.value == "escalated"

    def test_non_triage_checkpoint_with_no_provider_still_escalates(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.seal_checkpoint(manifest.runId, "RATIFY", items=[], corpus_hash=manifest.corpusHash)
        run_store.write_checkpoint_decisions(manifest.runId, "RATIFY", [{"itemId": "x"}], complete=True)
        result = resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="RATIFY", run_store=run_store, settings=load_settings(), model_gateway=None,
        )
        assert result.state == "AWAIT_MODEL_PROVIDER"


class TestResumeAfterCheckpointFullContinuation:
    """Exercises the real TRIAGE continuation (ACORD Aligner degraded,
    Canonical Synthesiser, coverage/gap computation) with a scripted
    model gateway - hermetic, no live network, matching every other
    agent's own established test pattern in this repo."""

    def test_continuation_produces_real_candidates_and_reaches_candidates_ready(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)

        result = resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )

        assert result.state == "CANDIDATES_READY"
        candidates = run_store.read_candidates(manifest.runId)
        assert candidates, "expected at least one real candidate"
        assert all(c.placement.value == "core" for c in candidates)

    def test_a_guardrail_rejection_on_one_cluster_does_not_abort_the_others(self, tmp_path: Path) -> None:
        # The "status" cluster's own real proposedConcept name ("status")
        # trips algorithms/naming.py's own documented, intentionally
        # trigger-happy region-marker check ("us" matches inside
        # "status") - a real, expected guardrail rejection, not a test
        # bug. Every other cluster must still synthesise successfully.
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)
        clusters_before = run_store.read_clusters(manifest.runId)

        resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )

        candidates = run_store.read_candidates(manifest.runId)
        assert len(candidates) == len(clusters_before) - 1
        events = run_store.read_journal_events(manifest.runId)
        assert any(e.stage == "S6" and e.outcome is not None and e.outcome.value == "escalated" for e in events)

    def test_coverage_stage_is_journalled_with_a_real_score(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)

        resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )

        events = run_store.read_journal_events(manifest.runId)
        s7 = next(e for e in events if e.stage == "S7")
        assert s7.detail is not None and "coverage score" in s7.detail

    def test_review_band_material_stays_sealed_not_auto_resolved(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        triage_before = run_store.read_triage_entries(manifest.runId)
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)

        resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )

        assert run_store.read_triage_entries(manifest.runId) == triage_before

    def test_agent_escalation_triage_entries_are_not_treated_as_review_pairs(self, tmp_path: Path) -> None:
        from pipeline.run_store import TriageEntry

        run_store, manifest = _create(tmp_path)
        run_store.append_triage_entry(
            manifest.runId,
            TriageEntry(kind="agent-escalation", reason="homonym", member_attribute_ids=("x",), cluster_payload={"x": 1}),
        )
        run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)

        # Must not raise trying to treat the escalation entry as a pair
        # (member_attribute_ids has only one element, unlike a real pair).
        result = resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )
        assert result.state == "CANDIDATES_READY"

    def test_non_triage_checkpoint_with_a_real_provider_is_a_pure_no_op(self, tmp_path: Path) -> None:
        run_store, manifest = _create(tmp_path)
        run_store.seal_checkpoint(manifest.runId, "RATIFY", items=[], corpus_hash=manifest.corpusHash)
        run_store.write_checkpoint_decisions(manifest.runId, "RATIFY", [{"itemId": "x"}], complete=True)
        before = run_store.read_run_manifest(manifest.runId)

        result = resume_after_checkpoint(
            run_id=manifest.runId, checkpoint="RATIFY", run_store=run_store,
            settings=load_settings(), model_gateway=_scripted_model_gateway(),
        )

        assert result == before
        assert run_store.read_candidates(manifest.runId) == []
