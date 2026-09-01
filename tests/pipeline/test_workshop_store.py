"""Hermetic tests for pipeline/workshop_store.py. Does not duplicate
emit/workshop_pack.py's own writing logic - assemble_pack() is called
directly against store.pack_dir(...), matching how the real API layer
will use it; this only tests the store's own read-back and
decision-recording responsibilities."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from emit.release import build_release_manifest
from emit.workshop_pack import assemble_pack
from pipeline.workshop_store import WorkshopStore

_EVREF = f"evref://uk/git/art-1@{'a' * 16}#/x"


def _candidate() -> C8Canonicalcandidate:
    return C8Canonicalcandidate.model_validate({
        "candidateId": "canon://Claim.claimId", "entity": "Claim", "attribute": "claimId",
        "dataType": "string", "cardinality": "1..1", "obligation": {"level": "mandatory"},
        "placement": "core", "placementRule": "1", "namingSource": "derived", "rationale": "x",
        "clusterRefs": ["cluster://claim-id"], "weight": 5,
        "ratification": {"status": "approved", "sme": "Jane", "decidedAt": "2026-01-01T00:00:00Z"},
    })


def _cluster() -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": "cluster://claim-id", "proposedConcept": "claimId",
        "members": [{"attributeId": "attr://uk/art-1/Claim.x", "region": "uk", "role": "core", "pairScore": 1.0}],
        "confidence": 0.9, "evidenceRefs": [_EVREF],
    })


def _coverage() -> C9Coveragereport:
    return C9Coveragereport.model_validate({
        "domain": "claims", "score": 0.95, "denominator": 1, "weightSum": 5.0,
        "perRegion": {"us": 1.0, "uk": 1.0, "eu": 1.0}, "gate1Pass": True, "gate2Pass": True, "gate3Pass": True,
        "specifiedVsInferred": {"specified": 1, "inferred": 0}, "exclusions": [],
    })


def _assemble_real_pack(pack_dir: Path) -> None:
    release = build_release_manifest(
        domain="claims", version="1.0.0", run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44",
        corpus_hash="sha256:abc", pins={}, artefacts=[], coverage_score=0.95,
        gate1=True, gate2=True, gate3=True, acord_conformance=0.0,
        signed_at="2026-01-01T00:00:00+00:00", signature="sig:placeholder",
    )
    assemble_pack(
        pack_dir, domain="claims", version="1.0", candidates=[_candidate()], clusters=[_cluster()],
        mapping_specs={}, round_trip_summaries={}, coverage_report=_coverage(), gap_register=[],
        release_manifest=release,
    )


class TestWorkshopRecord:
    def test_write_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        destination = store.write_workshop(workshop_id, {"runId": "x", "domain": "claims"})
        assert destination == tmp_path / str(workshop_id) / "workshop.json"

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        record = {"runId": "x", "domain": "claims", "checkpoint": "RATIFY", "participants": []}
        store.write_workshop(workshop_id, record)
        assert store.read_workshop(workshop_id) == record

    def test_relative_base_path_resolves_against_repo_root(self) -> None:
        store = WorkshopStore(base_path="workshop-store")
        assert store.workshop_dir(uuid4()).is_absolute()


class TestPackReadBack:
    def test_pack_dir_is_where_assemble_pack_writes(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        _assemble_real_pack(store.pack_dir(workshop_id))
        assert (store.pack_dir(workshop_id) / "workshop-pack-manifest.json").is_file()
        assert (store.pack_dir(workshop_id) / "Claim.json").is_file()

    def test_read_pack_manifest_round_trips_a_real_assembled_pack(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        _assemble_real_pack(store.pack_dir(workshop_id))

        manifest = store.read_pack_manifest(workshop_id)
        assert manifest.domain == "claims"
        assert manifest.version == "1.0"
        assert any(f.path == "Claim.json" for f in manifest.files)


class TestDecisions:
    def test_read_with_no_decisions_returns_empty_list(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        assert store.read_decisions(uuid4()) == []

    def test_append_then_read_round_trips(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        decisions = [{"candidateId": "canon://Claim.claimId", "outcome": "accept", "rationale": "r", "sme": "Jane"}]
        store.append_decisions(workshop_id, decisions)
        assert store.read_decisions(workshop_id) == decisions

    def test_repeated_appends_accumulate(self, tmp_path: Path) -> None:
        store = WorkshopStore(base_path=tmp_path)
        workshop_id = uuid4()
        store.append_decisions(workshop_id, [{"candidateId": "a"}])
        store.append_decisions(workshop_id, [{"candidateId": "b"}, {"candidateId": "c"}])
        assert len(store.read_decisions(workshop_id)) == 3
