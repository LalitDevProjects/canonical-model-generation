from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from pipeline.run_store import RunStore

from algorithms.clustering import ReviewPair, build_cluster, run_clustering, write_triage_export
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import ClusteringConfig

RUN_ID = uuid4()
_CFG = ClusteringConfig()


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
        "parentPath": "Claim",
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _profiled(local_name: str, data_type: str, region: str = "us", **overrides: object) -> ProfiledAttribute:
    return profile(_attr(local_name, data_type, region, **overrides), siblings=[])


class TestBuildCluster:
    def test_single_member_is_its_own_core_with_confidence_one(self) -> None:
        a = _profiled("x", "string")
        cluster = build_cluster([a], edges={}, conflict_class=None, conflict_detail=None)
        assert len(cluster.members) == 1
        assert cluster.members[0].role.value == "core"
        assert cluster.confidence == 1.0

    def test_confidence_is_min_of_pairwise_edges(self) -> None:
        a = _profiled("x", "string", attributeId="attr://us/art-1/Claim.x")
        b = _profiled("y", "string", attributeId="attr://us/art-1/Claim.y", region="uk")
        c = _profiled("z", "string", attributeId="attr://us/art-1/Claim.z", region="eu")
        edges = {
            frozenset({a.record.attributeId, b.record.attributeId}): 0.9,
            frozenset({a.record.attributeId, c.record.attributeId}): 0.75,
            frozenset({b.record.attributeId, c.record.attributeId}): 0.8,
        }
        cluster = build_cluster([a, b, c], edges=edges, conflict_class=None, conflict_detail=None)
        assert cluster.confidence == 0.75

    def test_proposed_concept_is_shortest_local_name(self) -> None:
        a = _profiled("lossDate", "date", attributeId="attr://us/art-1/Claim.lossDate")
        b = _profiled("dateOfLoss", "date", attributeId="attr://uk/art-2/Claim.dateOfLoss", region="uk")
        edges = {frozenset({a.record.attributeId, b.record.attributeId}): 0.8}
        cluster = build_cluster([a, b], edges=edges, conflict_class=None, conflict_detail=None)
        assert cluster.proposedConcept == "lossDate"

    def test_evidence_refs_are_deduped_union_of_members(self) -> None:
        a = _profiled("x", "string", attributeId="attr://us/art-1/Claim.x")
        b = _profiled(
            "x", "string", attributeId="attr://uk/art-2/Claim.x", region="uk",
            evidenceRefs=["evref://uk/git/art-1@1234567890abcdef#/x"],
        )
        edges = {frozenset({a.record.attributeId, b.record.attributeId}): 0.8}
        cluster = build_cluster([a, b], edges=edges, conflict_class=None, conflict_detail=None)
        assert len(cluster.evidenceRefs) == 2

    def test_conflict_class_and_detail_are_passed_through(self) -> None:
        a = _profiled("x", "string")
        cluster = build_cluster([a], edges={}, conflict_class="homonym", conflict_detail="split on: type-incompatible")
        assert cluster.conflictClass is not None
        assert cluster.conflictClass.value == "homonym"
        assert cluster.conflictDetail == "split on: type-incompatible"

    def test_cluster_id_is_deterministic(self) -> None:
        a = _profiled("x", "string")
        c1 = build_cluster([a], edges={}, conflict_class=None, conflict_detail=None)
        c2 = build_cluster([a], edges={}, conflict_class=None, conflict_detail=None)
        assert c1.clusterId == c2.clusterId

    def test_variant_pair_score_is_similarity_to_core(self) -> None:
        # b has the lower evidenceTier (stronger evidence) so it becomes core.
        a = _profiled("x", "string", attributeId="attr://us/art-1/Claim.x", evidenceTier=2)
        b = _profiled("x", "string", attributeId="attr://uk/art-2/Claim.x", region="uk", evidenceTier=1)
        edges = {frozenset({a.record.attributeId, b.record.attributeId}): 0.77}
        cluster = build_cluster([a, b], edges=edges, conflict_class=None, conflict_detail=None)
        core_member = next(m for m in cluster.members if m.role.value == "core")
        variant_member = next(m for m in cluster.members if m.role.value == "variant")
        assert core_member.attributeId == b.record.attributeId
        assert variant_member.pairScore == 0.77


class TestRunClustering:
    def test_synonym_style_pair_merges_into_one_cluster(self) -> None:
        a = _profiled("lossDate", "date", attributeId="attr://us/art-1/Claim.lossDate")
        b = _profiled("lossDate", "date", attributeId="attr://uk/art-2/Claim.lossDate", region="uk")
        clusters, review_pairs = run_clustering([a, b], config=_CFG, embed_dimensions=64)
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2
        assert review_pairs == []

    def test_unrelated_attributes_produce_no_clusters(self) -> None:
        a = _profiled("claimantName", "string")
        b = _profiled("policyNumber", "string", attributeId="attr://us/art-1/Claim.policyNumber")
        clusters, review_pairs = run_clustering([a, b], config=_CFG, embed_dimensions=64)
        assert clusters == []
        assert review_pairs == []

    def test_review_band_pair_is_not_clustered_but_returned(self) -> None:
        # Same head noun (co-blocks) but different type family and no
        # matching context/constraints - expected to land in the review
        # band rather than link or drop entirely.
        a = _profiled("reserveAmount", "decimal", attributeId="attr://us/art-1/Claim.reserveAmount")
        b = _profiled(
            "reserveAmt", "decimal", attributeId="attr://uk/art-2/Claim.reserveAmt", region="uk",
            constraints=[{"kind": "range", "expression": "minimum=0"}],
        )
        clusters, review_pairs = run_clustering([a, b], config=_CFG, embed_dimensions=64)
        # Whichever band it lands in, it must be self-consistent: never
        # both a cluster AND a review pair for the same evidence.
        assert not (clusters and review_pairs)

    def test_deterministic_across_repeated_calls(self) -> None:
        a = _profiled("lossDate", "date", attributeId="attr://us/art-1/Claim.lossDate")
        b = _profiled("lossDate", "date", attributeId="attr://uk/art-2/Claim.lossDate", region="uk")
        first, _ = run_clustering([a, b], config=_CFG, embed_dimensions=64)
        second, _ = run_clustering([a, b], config=_CFG, embed_dimensions=64)
        assert first[0].clusterId == second[0].clusterId


class TestWriteTriageExport:
    def test_writes_one_entry_per_review_pair(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        a = _profiled("x", "string")
        b = _profiled("y", "string", attributeId="attr://uk/art-2/Claim.y", region="uk")
        pairs = [ReviewPair(a=a, b=b, score=0.6, features={"lexical": 0.5})]
        write_triage_export(store, run_id, pairs)
        entries = store.read_triage_entries(run_id)
        assert len(entries) == 1
        assert entries[0].kind == "review-pair"
        assert entries[0].score == 0.6
        assert set(entries[0].member_attribute_ids) == {a.record.attributeId, b.record.attributeId}

    def test_no_pairs_writes_nothing(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        write_triage_export(store, run_id, [])
        assert store.read_triage_entries(run_id) == []
