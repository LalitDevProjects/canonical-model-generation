"""Shared builders for emit/ tests - real C6/C7/C8/C9/C10 instances."""

from __future__ import annotations

from typing import Any

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C9.GapEntry._1_0 import C9Gapentry

_EVREF = f"evref://uk/git/art-1@{'a' * 16}#/x"


def candidate(
    *,
    entity: str = "Claim",
    attribute: str = "claimId",
    data_type: str = "string",
    obligation: str = "mandatory",
    placement: str = "core",
    weight: int = 5,
    rationale: str = "The claim reference",
    ratification_status: str = "approved",
    sme: str | None = "Jane",
    decided_at: str | None = "2026-01-01T00:00:00Z",
    cluster_refs: list[str] | None = None,
) -> C8Canonicalcandidate:
    rule = {"core": "1", "extension:us": "4", "extension:uk": "4", "extension:eu": "4"}[placement]
    return C8Canonicalcandidate.model_validate({
        "candidateId": f"canon://{entity}.{attribute}",
        "entity": entity,
        "attribute": attribute,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": obligation},
        "placement": placement,
        "placementRule": rule,
        "namingSource": "derived",
        "rationale": rationale,
        "clusterRefs": cluster_refs or [f"cluster://{entity.lower()}-{attribute.lower()}"],
        "weight": weight,
        "ratification": {"status": ratification_status, "sme": sme, "decidedAt": decided_at},
    })


def cluster(*, cluster_id: str = "claim-id", region: str = "uk") -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": cluster_id,
        "members": [{"attributeId": f"attr://{region}/art-1/Claim.x", "region": region, "role": "core", "pairScore": 1.0}],
        "confidence": 0.9,
        "evidenceRefs": [_EVREF],
    })


def alignment(*, cluster_id: str = "claim-id", verdict: str = "unassessed") -> C7Alignmentrecord:
    return C7Alignmentrecord.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "acordRef": None,
        "verdict": verdict,
        "deviation": None,
        "rationale": "ACORD ingestion not permitted",
        "evidenceRefs": [_EVREF],
    })


def coverage_report(**overrides: Any) -> C9Coveragereport:
    payload: dict[str, Any] = {
        "domain": "claims", "score": 0.95, "denominator": 1, "weightSum": 5.0,
        "perRegion": {"us": 1.0, "uk": 1.0, "eu": 1.0},
        "gate1Pass": True, "gate2Pass": True, "gate3Pass": True,
        "specifiedVsInferred": {"specified": 1, "inferred": 0}, "exclusions": [],
    }
    payload.update(overrides)
    return C9Coveragereport.model_validate(payload)


def gap_entry(**overrides: Any) -> C9Gapentry:
    payload: dict[str, Any] = {"conceptId": "cluster://x", "weight": 1, "reason": "excluded", "affectedRegions": ["uk"]}
    payload.update(overrides)
    return C9Gapentry.model_validate(payload)
