"""
Increment 7's literal acceptance test (Section 17.2): "Planted synonyms
cluster; the planted homonym does not merge." Runs entirely against the
real golden/clustering/{us,uk,eu}/claim.yaml fixtures through the real
parsers.router.parse -> algorithms.profiling.profile ->
algorithms.clustering.run_clustering path - zero LLM, zero DB (api=None),
per this increment's confirmed architecture: the deterministic pipeline
alone must satisfy both clauses.

golden/clustering/README-worthy design, spelled out here since there is
no separate fixture README: lossDate (US) / dateOfLoss (UK) /
dateSurvenance (EU) are the planted synonym triple, sharing a parent
path, sibling attributes and a declared date-pattern constraint so the
deterministic score clears LINK_THRESHOLD despite differing (and, for
dateSurvenance, non-English) local names. Claim.metadata.claimDate is
the planted homonym: present with the SAME local name and parent shape
in both UK and EU, scoring high enough on name/context alone to connect
in the graph, but genuinely divergent (UK: mandatory dateTime, "when the
record was created"; EU: optional string, "a policy-administration
reference date") - exactly what split_on_homonym_signals must catch.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.clustering import run_clustering
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import load_settings
from parsers.router import parse

GOLDEN_CLUSTERING_DIR = Path(__file__).resolve().parents[2] / "golden" / "clustering"


def _make_artefact(region: str, artefact_id: str) -> C1Sourceartefact:
    return C1Sourceartefact.model_validate({
        "artefactId": artefact_id,
        "region": region,
        "system": "git",
        "uri": f"git://example/{artefact_id}",
        "version": "abc1234",
        "contentHash": "a" * 64,
        "mediaType": "application/vnd.oai.openapi",
        "evidenceTier": 1,
        "sanitisation": {
            "artefactId": artefact_id,
            "contentHash": "a" * 64,
            "labels": ["STRUCTURAL"],
            "verdict": "allow",
            "licenceDisposition": "permitted",
            "policyVersion": 1,
            "classifiedAt": "2026-08-20T09:00:00Z",
        },
    })


def _profile_golden_clustering_corpus(run_id: UUID) -> list[ProfiledAttribute]:
    """Parses every golden/clustering/{region}/claim.yaml through the
    real OpenAPI parser, then profiles each record with siblings drawn
    from other records sharing the same parentPath WITHIN that region's
    own artefact (siblings are a per-document notion - Section 9.1's own
    profile(rec, siblings) is called once per artefact's parse in a real
    pipeline, not across the whole corpus)."""
    profiled: list[ProfiledAttribute] = []
    for region in ("us", "uk", "eu"):
        content = (GOLDEN_CLUSTERING_DIR / region / "claim.yaml").read_bytes()
        artefact = _make_artefact(region, f"claims-clustering-{region}")
        records: list[C5Attributerecord] = parse(content, artefact, run_id)
        by_parent: dict[str | None, list[C5Attributerecord]] = defaultdict(list)
        for record in records:
            by_parent[record.parentPath].append(record)
        for record in records:
            siblings = [s for s in by_parent[record.parentPath] if s.attributeId != record.attributeId]
            profiled.append(profile(record, siblings=siblings))
    return profiled


class TestPlantedSynonymsClusterAndPlantedHomonymDoesNotMerge:
    def test_acceptance(self) -> None:
        run_id = uuid4()
        settings = load_settings()
        profiled = _profile_golden_clustering_corpus(run_id)

        clusters, review_pairs = run_clustering(
            profiled,
            run_id=str(run_id),
            api=None,
            config=settings.clustering,
            embed_dimensions=settings.models.embedding_dimensions,
        )

        names_by_cluster_id = {
            str(c.clusterId): {str(m.attributeId).rsplit(".", 1)[-1] for m in c.members} for c in clusters
        }
        clusters_by_id = {str(c.clusterId): c for c in clusters}

        # Clause 1: "Planted synonyms cluster" - lossDate/dateOfLoss/
        # dateSurvenance land in exactly one cluster together, with no
        # conflict fired (a clean synonym merge).
        synonym_names = {"lossDate", "dateOfLoss", "dateSurvenance"}
        synonym_cluster_ids = [cid for cid, names in names_by_cluster_id.items() if synonym_names & names]
        assert len(synonym_cluster_ids) == 1, f"expected exactly one cluster touching the synonym triple, got {synonym_cluster_ids}"
        synonym_cluster = clusters_by_id[synonym_cluster_ids[0]]
        assert names_by_cluster_id[synonym_cluster_ids[0]] == synonym_names
        assert synonym_cluster.conflictClass is None or synonym_cluster.conflictClass.value == "synonym"

        # Clause 2: "the planted homonym does not merge" - the two
        # claimDate attributeIds never appear together in the same
        # cluster (whether they end up unconnected, or connected-then-
        # split via a fired homonym signal).
        claim_date_cluster_ids = [cid for cid, names in names_by_cluster_id.items() if "claimDate" in names]
        for cid in claim_date_cluster_ids:
            member_ids = {str(m.attributeId) for m in clusters_by_id[cid].members}
            claim_date_members = {i for i in member_ids if i.endswith("claimDate")}
            assert len(claim_date_members) <= 1, f"both claimDate homonyms merged into {cid}"
        # If they ended up connected at all, the split must have been
        # attributed to a real homonym signal, not silently dropped.
        claim_date_clusters = [clusters_by_id[cid] for cid in claim_date_cluster_ids]
        if len(claim_date_clusters) == 2 and all(c.conflictClass is not None for c in claim_date_clusters):
            assert all(c.conflictClass.value == "homonym" for c in claim_date_clusters)  # type: ignore[union-attr]
