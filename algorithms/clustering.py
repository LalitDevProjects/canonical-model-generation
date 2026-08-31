"""
Clustering (Section 9.4 - "Core Algorithms"). run_clustering() is the
full deterministic pipeline: build_blocks (9.2) -> similarity (9.3) ->
graph connected-components -> homonym split (9.5) -> conflict
classification (9.5) -> real generated.C6.ConceptCluster objects.

"Connected components are permissive by design; the homonym split
immediately afterwards is what makes that safe."

Review-band pairs (score in [review_band_low, link_threshold)) are "not
discarded: they become triage input" - write_triage_export() persists
them via pipeline/run_store.py::TriageEntry, Increment 7's own "triage
export" deliverable. Confirmed architecture (this session): this whole
module is self-sufficient with zero LLM dependency - the Semantic
Resolver agent (Increment 7's other half) adjudicates only the
review-band material this module sets aside, exactly mirroring how
Repository Scout (Increment 6) adjudicates connectors/relevance.py's own
"uncertain" middle band.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from uuid import UUID

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster

from algorithms.blocking import NeighboursApi, build_blocks
from algorithms.conflict import classify_conflict, split_on_homonym_signals
from algorithms.graph import connected_components
from algorithms.profiling import ProfiledAttribute
from algorithms.similarity import compute_embeddings, similarity
from config.settings import ClusteringConfig
from contracts.validators import canonical_json_bytes, unwrap_ref
from pipeline.run_store import RunStore, TriageEntry


@dataclass(frozen=True)
class ReviewPair:
    a: ProfiledAttribute
    b: ProfiledAttribute
    score: float
    features: dict[str, float]


def _cluster_id(member_attribute_ids: Sequence[str]) -> str:
    digest = sha256(canonical_json_bytes(sorted(member_attribute_ids))).hexdigest()
    return f"cluster://cl-{digest[:16]}"


def _pick_core(group: Sequence[ProfiledAttribute], edges: Mapping[frozenset[str], float]) -> ProfiledAttribute:
    """Exactly one 'core' member per cluster - the member with the
    lowest evidenceTier (strongest evidence), tie-broken by the highest
    mean pairwise similarity to the rest of the group (most "central"),
    then by lexicographically-first attributeId for full determinism.
    Not spec-mandated - a documented, provisional rule pending a real
    synthesis pass (Canonical Synthesiser, Increment 8/9)."""
    if len(group) == 1:
        return group[0]

    def mean_similarity(member: ProfiledAttribute) -> float:
        scores = [
            edges[pair]
            for other in group
            if other is not member
            and (pair := frozenset({member.record.attributeId, other.record.attributeId})) in edges
        ]
        return sum(scores) / len(scores) if scores else 0.0

    return min(group, key=lambda m: (m.record.evidenceTier, -mean_similarity(m), m.record.attributeId))


def _confidence(group: Sequence[ProfiledAttribute], edges: Mapping[frozenset[str], float]) -> float:
    """The min of the group's own pairwise edge scores - conservative,
    consistent with the spec's own "a wrongly merged pair ships a
    defect" bias, and reads naturally against guardrail G2's
    confidence >= 0.80 threshold (Section 7.5.1)."""
    if len(group) < 2:
        return 1.0
    pairwise_scores = [
        edges[pair] for a, b in combinations(group, 2) if (pair := frozenset({a.record.attributeId, b.record.attributeId})) in edges
    ]
    return min(pairwise_scores) if pairwise_scores else 0.0


def build_cluster(
    group: Sequence[ProfiledAttribute],
    *,
    edges: Mapping[frozenset[str], float],
    conflict_class: str | None,
    conflict_detail: str | None,
) -> C6Conceptcluster:
    """Assembles a real C6Conceptcluster from a (post-homonym-split,
    conflict-classified) group of ProfiledAttributes. clusterId is
    content-addressed (deterministic, reproducible across runs over the
    same evidence); proposedConcept is the shortest member localName (a
    provisional naming heuristic, pending Canonical Synthesiser's real
    naming pass); each member's pairScore is its similarity to the
    cluster's own core member (1.0 for the core itself, which has no
    natural "pair" against itself)."""
    core = _pick_core(group, edges)
    confidence = _confidence(group, edges)
    proposed_concept = min((m.record.localName for m in group), key=lambda name: (len(name), name))
    evidence_refs = sorted({str(unwrap_ref(ref)) for m in group for ref in m.record.evidenceRefs})

    members_payload = []
    for m in group:
        if m is core:
            pair_score = 1.0
        else:
            pair = frozenset({m.record.attributeId, core.record.attributeId})
            pair_score = edges.get(pair, confidence)
        members_payload.append(
            {
                "attributeId": m.record.attributeId,
                "region": m.record.region.value,
                "role": "core" if m is core else "variant",
                "pairScore": pair_score,
            }
        )

    payload: dict[str, object] = {
        "clusterId": _cluster_id([m.record.attributeId for m in group]),
        "proposedConcept": proposed_concept,
        "members": members_payload,
        "confidence": confidence,
        "evidenceRefs": evidence_refs,
    }
    if conflict_class is not None:
        payload["conflictClass"] = conflict_class
    if conflict_detail is not None:
        payload["conflictDetail"] = conflict_detail
    return C6Conceptcluster.model_validate(payload)


def run_clustering(
    attrs: Sequence[ProfiledAttribute],
    *,
    run_id: str | None = None,
    api: NeighboursApi | None = None,
    config: ClusteringConfig,
    embed_dimensions: int,
) -> tuple[list[C6Conceptcluster], list[ReviewPair]]:
    """Section 9.4's cluster(), fully wired against this repo's real
    blocking/similarity/conflict modules. api/run_id are optional and
    degrade the embedding blocking key only (see
    algorithms.blocking.build_blocks) - this function runs entirely
    hermetically (no DB, no LLM) when they're omitted."""
    blocks = build_blocks(attrs, run_id=run_id, api=api, config=config)
    embeddings = compute_embeddings(attrs, dimensions=embed_dimensions)
    by_id = {a.record.attributeId: a for a in attrs}

    edges: dict[frozenset[str], float] = {}
    review_pairs: list[ReviewPair] = []
    seen_pairs: set[frozenset[str]] = set()

    for block in blocks:
        for a, b in combinations(block.members, 2):
            pair = frozenset({a.record.attributeId, b.record.attributeId})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            score, features = similarity(a, b, embeddings=embeddings, config=config)
            if score >= config.link_threshold:
                edges[pair] = score
            elif score >= config.review_band_low:
                review_pairs.append(ReviewPair(a=a, b=b, score=score, features=features))

    linked_ids = sorted({attribute_id for pair in edges for attribute_id in pair})
    clusters: list[C6Conceptcluster] = []
    for component_ids in connected_components(linked_ids, edges):
        members = [by_id[i] for i in component_ids]
        for group_result in split_on_homonym_signals(members, edges, config):
            group = list(group_result.members)
            conflict_class, conflict_detail = group_result.conflict_class, group_result.conflict_detail
            if conflict_class is None:
                conflict_class, conflict_detail = classify_conflict(group, config)
            clusters.append(build_cluster(group, edges=edges, conflict_class=conflict_class, conflict_detail=conflict_detail))

    return clusters, review_pairs


def write_triage_export(run_store: RunStore, run_id: UUID, review_pairs: Sequence[ReviewPair]) -> None:
    """Section 9.4's emit_review_queue(), realised as the concrete
    on-disk artefact pipeline/run_store.py::TriageEntry describes -
    Increment 7's own "triage export" deliverable."""
    for pair in review_pairs:
        run_store.append_triage_entry(
            run_id,
            TriageEntry(
                kind="review-pair",
                reason=f"similarity score {pair.score:.3f} in the review band; not auto-linked",
                member_attribute_ids=(pair.a.record.attributeId, pair.b.record.attributeId),
                score=pair.score,
                features=pair.features,
            ),
        )
