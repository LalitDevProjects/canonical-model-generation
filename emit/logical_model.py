"""
Section 11.3's logical model export: JSON-LD, independent of any wire
format, carrying lineage "in both directions: back to the evidence,
forward to the schema element that realises it."

Built entirely from real C8 CanonicalCandidate data plus two caller-
supplied maps this module has no way to derive on its own:
`evidence_by_candidate` (a candidate's own evidence traces through its
ConceptCluster - C8 carries no evidenceRefs field of its own, the same
gap `algorithms/coverage.py::build_universe` already documents) and
`alignment_by_entity` (a real C7 AlignmentRecord is keyed by clusterId,
not entity - resolving many clusters to one entity's own single
`acordAlignment` slot is a caller policy decision, not something this
module should invent). Neither map needs a live substrate query to
build - both are assembled once from data the caller already has in hand,
keeping this module itself fully hermetic.

`ratifiedBy.session` has no real source field anywhere in this repo's
data model (C8's own `ratification` carries `sme`/`decidedAt`, not a
named workshop session) - `ratification.decidedAt` is used in its place,
the same class of honest, documented substitution as
`algorithms/coverage.py::sole_region()`'s own tie-break.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate

from contracts.validators import unwrap_ref

_CONTEXT_BASE = "https://canonicalmodel.internal/canonical/context"


def _acord_alignment(record: C7Alignmentrecord) -> dict[str, Any]:
    alignment: dict[str, Any] = {"verdict": record.verdict.value}
    if record.acordRef is not None:
        alignment["ref"] = str(unwrap_ref(record.acordRef))
    if record.deviation is not None:
        alignment["deviation"] = record.deviation
    return alignment


def _attribute_entry(
    candidate: C8Canonicalcandidate,
    *,
    domain: str,
    version: str,
    entity_schema_path: str,
    evidence: list[str],
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "@id": f"logical:{domain}/{candidate.entity}.{candidate.attribute}",
        "label": candidate.attribute,
        "datatype": candidate.dataType.value,
        "obligation": candidate.obligation.level.value,
        "weight": int(candidate.weight),
        "realisedBy": f"{entity_schema_path}#/properties/{candidate.attribute}",
    }
    if evidence:
        entry["derivedFrom"] = evidence
    if candidate.ratification.status.value == "approved" and candidate.ratification.sme:
        ratified: dict[str, Any] = {"sme": candidate.ratification.sme}
        if candidate.ratification.decidedAt is not None:
            ratified["session"] = candidate.ratification.decidedAt.isoformat()
        entry["ratifiedBy"] = ratified
    return entry


def build_logical_model(
    candidates: list[C8Canonicalcandidate],
    *,
    domain: str,
    version: str,
    entity_schema_paths: Mapping[str, str],
    evidence_by_candidate: Mapping[str, list[str]] | None = None,
    alignment_by_entity: Mapping[str, C7Alignmentrecord] | None = None,
    entity_definitions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    evidence_by_candidate = evidence_by_candidate or {}
    alignment_by_entity = alignment_by_entity or {}
    entity_definitions = entity_definitions or {}

    by_entity: dict[str, list[C8Canonicalcandidate]] = {}
    for candidate in candidates:
        by_entity.setdefault(candidate.entity, []).append(candidate)

    entities: list[dict[str, Any]] = []
    for entity in sorted(by_entity):
        group = by_entity[entity]
        entity_entry: dict[str, Any] = {
            "@id": f"logical:{domain}/{entity}",
            "label": entity,
        }
        if entity in entity_definitions:
            entity_entry["definition"] = entity_definitions[entity]
        if entity in alignment_by_entity:
            entity_entry["acordAlignment"] = _acord_alignment(alignment_by_entity[entity])
        entity_entry["attributes"] = [
            _attribute_entry(
                candidate,
                domain=domain,
                version=version,
                entity_schema_path=entity_schema_paths.get(entity, f"{entity}.json"),
                evidence=evidence_by_candidate.get(str(candidate.candidateId), []),
            )
            for candidate in sorted(group, key=lambda c: c.attribute)
        ]
        entities.append(entity_entry)

    return {
        "@context": f"{_CONTEXT_BASE}/{version}.jsonld",
        "@id": f"logical:{domain}/{version}",
        "entities": entities,
    }
