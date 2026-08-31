"""
Coverage computation and the gap register (Section 9.8 - "Core
Algorithms"). "Unevidenced concepts stay in the denominator: removing
them would let the score rise by hiding work." "Never let the
denominator move quietly - every mechanism that shrinks the attribute
universe - exclusions, inference floors, unresolved concepts - MUST be
reported alongside the score. A coverage figure published without its
denominator and exclusion register is not a valid report under this
specification, and reviewers should reject it."

Concept is not a C-numbered contract - like Increment 3's
ProfiledAttribute or Increment 7's Block, it's a pure internal algorithm
structure, one per ConceptCluster (a cluster is always exactly one
universe item, whether or not synthesis produced a candidate for it -
"the concept returns to triage" when it doesn't is Canonical
Synthesiser's own [UNCERTAINTY] language for exactly this "gap"
resolution).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C9.GapEntry._1_0 import C9Gapentry
from generated.common.defs import ExclusionEntry, Level

from config.settings import CoverageConfig
from contracts.validators import unwrap_ref
from substrate.api import SubstrateApi

Resolution = Literal["core", "extension", "gap"]

_OBLIGATION_STRENGTH: dict[Level, int] = {Level.mandatory: 3, Level.conditional: 2, Level.optional: 1}
_WEIGHT_FROM_OBLIGATION: dict[Level, Literal[5, 3, 1]] = {Level.mandatory: 5, Level.conditional: 3, Level.optional: 1}


@dataclass(frozen=True)
class Concept:
    concept_id: str
    weight: Literal[5, 3, 1]
    evidence_refs: tuple[str, ...]
    ratifying_sme: str | None
    resolution: Resolution
    regions: frozenset[str]
    inferred: bool


def weight_from_obligation(level: Level) -> Literal[5, 3, 1]:
    return _WEIGHT_FROM_OBLIGATION[level]


def strongest_obligation(records: Sequence[C5Attributerecord]) -> Level:
    if not records:
        return Level.optional
    return max((r.obligation.level for r in records), key=lambda level: _OBLIGATION_STRENGTH[level])


def weakest_obligation(records: Sequence[C5Attributerecord]) -> Level:
    """Canonical Synthesiser's own Rule 3 / guardrail G5: "Choose the
    WEAKEST obligation present across regions... obligation.level MUST
    NOT be strengthened beyond the weakest regional obligation in the
    cluster." As deterministically computable as placement - the code
    supplies it, the same status as algorithms/placement.py::place()."""
    if not records:
        return Level.optional
    return min((r.obligation.level for r in records), key=lambda level: _OBLIGATION_STRENGTH[level])


def build_universe(
    clusters: Sequence[C6Conceptcluster],
    candidates_by_cluster_id: Mapping[str, C8Canonicalcandidate],
    *,
    substrate: SubstrateApi,
    run_id: str,
) -> list[Concept]:
    """One Concept per cluster. resolution="gap" when no candidate exists
    for it at all (Canonical Synthesiser declined to synthesise one);
    weight then has no real source, so it's derived from the strongest
    obligation level found across the cluster's own members - the only
    concept-agnostic anchor available. ratifying_sme is populated only
    when a human has actually approved the candidate
    (ratification.status == "approved") - "the platform proposes, humans
    ratify" working as intended, not a gap to route around."""
    universe: list[Concept] = []
    for cluster in clusters:
        cluster_id = str(unwrap_ref(cluster.clusterId))
        member_records = [substrate.get_attribute(run_id, str(m.attributeId)) for m in cluster.members]
        regions = frozenset(str(m.region.value) for m in cluster.members)
        evidence_refs = tuple(sorted({str(unwrap_ref(ref)) for ref in cluster.evidenceRefs}))
        inferred = bool(member_records) and all(r.inferred for r in member_records)

        candidate = candidates_by_cluster_id.get(cluster_id)
        if candidate is None:
            universe.append(Concept(
                concept_id=cluster_id,
                weight=weight_from_obligation(strongest_obligation(member_records)),
                evidence_refs=evidence_refs,
                ratifying_sme=None,
                resolution="gap",
                regions=regions,
                inferred=inferred,
            ))
            continue

        resolution: Resolution = "core" if str(candidate.placement) == "core" else "extension"
        ratifying_sme = candidate.ratification.sme if str(candidate.ratification.status) == "approved" else None
        weight_value = int(candidate.weight)
        assert weight_value in (5, 3, 1)
        universe.append(Concept(
            concept_id=str(unwrap_ref(candidate.candidateId)),
            weight=weight_value,  # type: ignore[arg-type]
            evidence_refs=evidence_refs,
            ratifying_sme=ratifying_sme,
            resolution=resolution,
            regions=regions,
            inferred=inferred,
        ))
    return universe


@dataclass(frozen=True)
class _Classification:
    mandatory_unresolved: tuple[Concept, ...]
    unevidenced: tuple[Concept, ...]
    resolved_r: dict[str, float]


def _resolution_score(resolution: Resolution, config: CoverageConfig) -> float:
    weights = config.resolution_weights
    return {"core": weights.core, "extension": weights.extension, "gap": weights.gap}[resolution]


def _classify(universe: Sequence[Concept], config: CoverageConfig) -> _Classification:
    mandatory_unresolved: list[Concept] = []
    unevidenced: list[Concept] = []
    resolved_r: dict[str, float] = {}
    for c in universe:
        if not c.evidence_refs or not c.ratifying_sme:
            unevidenced.append(c)
            r = 0.0
        else:
            r = _resolution_score(c.resolution, config)
        if c.weight == 5 and r < 1.0:
            mandatory_unresolved.append(c)  # Gate 1
        resolved_r[c.concept_id] = r
    return _Classification(tuple(mandatory_unresolved), tuple(unevidenced), resolved_r)


def _score(universe: Sequence[Concept], config: CoverageConfig) -> tuple[float, _Classification]:
    classification = _classify(universe, config)
    num = sum(c.weight * classification.resolved_r[c.concept_id] for c in universe)
    den = sum(c.weight for c in universe)
    return (num / den if den else 0.0), classification


def coverage(
    universe: Sequence[Concept],
    domain: str,
    *,
    exclusions: Sequence[ExclusionEntry] = (),
    config: CoverageConfig,
) -> C9Coveragereport:
    """Section 9.8's coverage(), against this repo's real Concept/
    CoverageConfig/ExclusionEntry shapes. per_region is computed via a
    private _score() helper rather than the pseudocode's own literal
    self-recursive coverage(universe_for(universe, rg), domain).score -
    behaviourally identical, without redundantly constructing and
    discarding three nested CoverageReport objects."""
    score, classification = _score(universe, config)
    den = sum(c.weight for c in universe)

    per_region: dict[str, float] = {}
    for region in ("us", "uk", "eu"):
        region_universe = [c for c in universe if region in c.regions]
        region_score, _ = _score(region_universe, config)
        per_region[region] = round(region_score, 4)

    specified = sum(1 for c in universe if not c.inferred)
    inferred_count = sum(1 for c in universe if c.inferred)

    return C9Coveragereport.model_validate({
        "domain": domain,
        "score": round(score, 4),
        "denominator": len(universe),
        "weightSum": den,
        "perRegion": per_region,
        "gate1Pass": not classification.mandatory_unresolved,
        "gate2Pass": score >= config.domain_target and all(v >= config.region_floor for v in per_region.values()),
        "gate3Pass": not classification.unevidenced,
        "specifiedVsInferred": {"specified": specified, "inferred": inferred_count},
        "exclusions": [e.model_dump(mode="json") for e in exclusions],
    })


def gap_register(
    universe: Sequence[Concept],
    report: C9Coveragereport,
    *,
    exclusions: Sequence[ExclusionEntry] = (),
    config: CoverageConfig,
) -> list[C9Gapentry]:
    """The gap register - Increment 8's own named deliverable, distinct
    from coverage() itself. Reuses coverage()'s own per-concept
    classification (via the same _classify() helper) rather than
    recomputing it. Four reasons, matching contracts/C9/GapEntry/1.0.json's
    existing enum: "unresolved" (Gate 1's own mandatory_unresolved),
    "unevidenced" (Gate 3's own list, excluding concepts already reported
    as unresolved so nothing is double-reported), "below-region-floor"
    (a non-core concept present in a region whose per_region score
    misses REGION_FLOOR), "excluded" (corpus-level exclusions, mapped by
    their own uri as the closest available identifier - an exclusion
    predates clustering entirely, so it has no real concept/region
    backing; a documented, provisional reading)."""
    classification = _classify(universe, config)
    unresolved_ids = {c.concept_id for c in classification.mandatory_unresolved}
    entries: list[C9Gapentry] = []

    for c in classification.mandatory_unresolved:
        entries.append(_gap_entry(c, "unresolved"))
    for c in classification.unevidenced:
        if c.concept_id in unresolved_ids:
            continue
        entries.append(_gap_entry(c, "unevidenced"))
    for region, score in report.perRegion.model_dump().items():
        if score >= config.region_floor:
            continue
        for c in universe:
            if region in c.regions and c.resolution != "core":
                entries.append(_gap_entry(c, "below-region-floor", regions=(region,)))
    for entry in exclusions:
        entries.append(C9Gapentry.model_validate({
            "conceptId": str(unwrap_ref(entry.uri)),
            "weight": 1,
            "reason": "excluded",
            "affectedRegions": ["us", "uk", "eu"],
            "recommendation": entry.detail if entry.detail else None,
        }))

    return entries


def _gap_entry(concept: Concept, reason: str, *, regions: Sequence[str] | None = None) -> C9Gapentry:
    return C9Gapentry.model_validate({
        "conceptId": concept.concept_id,
        "weight": concept.weight,
        "reason": reason,
        "affectedRegions": list(regions) if regions else sorted(concept.regions) or ["us"],
        "evidenceRefs": list(concept.evidence_refs),
    })
