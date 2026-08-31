"""
Section 11.1's emission rules, applied to real C8 CanonicalCandidate data:
one JSON Schema document per entity, `additionalProperties: false`
everywhere, extension points as `$ref`-only, deterministic serialisation.

C8's own `dataType` field stays constrained to the bare primitive enum
(string/integer/decimal/...) - the same documented gap
agents/canonical_synthesiser.py's own G2 guardrail already works around
(no room for "MonetaryAmount"/"Identifier" as first-class type names).
`_data_type_to_schema()` therefore emits a plain `{"type": "object"}` for
any candidate whose real value happens to be a MonetaryAmount/Identifier
shape - it has no signal to know otherwise, and inventing a naming
heuristic here would only paper over the same gap I8 already documented
rather than fix it. A future contract revision giving C8 a real
canonical-type-name field would let this module $ref
common_schemas.py's own MonetaryAmount/Identifier documents directly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate

_SCHEMA_BASE = "https://canonicalmodel.internal/canonical"

_DATA_TYPE_TO_SCHEMA: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "decimal": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "dateTime": {"type": "string", "format": "date-time"},
    "time": {"type": "string", "format": "time"},
    "duration": {"type": "string", "format": "duration"},
    "binary": {"type": "string", "contentEncoding": "base64"},
    "object": {"type": "object"},
    "array": {"type": "array"},
    "reference": {"type": "string"},
    "unknown": {},
}


def entity_schema_id(domain: str, version: str, entity: str) -> str:
    return f"{_SCHEMA_BASE}/{domain}/{version}/{entity}.json"


def extension_schema_id(domain: str, version: str, region: str, entity: str) -> str:
    return f"{_SCHEMA_BASE}/{domain}/{version}/extensions/{region}/{entity}Extension.json"


def serialise(doc: Any) -> bytes:
    """Section 11.1: "Sorted keys, two-space indent, LF endings. A re-run
    producing semantically identical output MUST produce byte-identical
    files." Encoded and returned as bytes (not written via a text-mode
    file handle) so no platform ever substitutes CRLF for the trailing
    newline. `doc` is any JSON-serialisable structure - a schema document
    (dict) or a plain list (e.g. the gap register)."""
    text = json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _property_schema(candidate: C8Canonicalcandidate, *, evidence: list[str]) -> dict[str, Any]:
    base = dict(_DATA_TYPE_TO_SCHEMA.get(candidate.dataType.value, {}))
    rationale = candidate.rationale.rstrip(". ")
    base["description"] = f"{rationale}. {candidate.candidateId}" if rationale else str(candidate.candidateId)
    if evidence:
        base["x-evidence"] = evidence
    return base


def build_entity_schemas(
    candidates: list[C8Canonicalcandidate],
    *,
    domain: str,
    version: str,
    evidence_by_candidate: Mapping[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """One schema per entity, core-placed attributes only - extension
    attributes are never inlined (Section 11.1: "Inlining types is
    prohibited... a region cannot add a property without a schema
    change")."""
    evidence_by_candidate = evidence_by_candidate or {}
    core_by_entity: dict[str, list[C8Canonicalcandidate]] = {}
    extension_regions_by_entity: dict[str, set[str]] = {}
    for candidate in candidates:
        placement = candidate.placement.value
        if placement == "core":
            core_by_entity.setdefault(candidate.entity, []).append(candidate)
        else:
            region = placement.split(":", 1)[1]
            extension_regions_by_entity.setdefault(candidate.entity, set()).add(region)

    schemas: dict[str, dict[str, Any]] = {}
    entities = set(core_by_entity) | set(extension_regions_by_entity)
    for entity in entities:
        core_candidates = core_by_entity.get(entity, [])
        properties: dict[str, Any] = {}
        required: list[str] = []
        for candidate in core_candidates:
            evidence = evidence_by_candidate.get(str(candidate.candidateId), [])
            properties[candidate.attribute] = _property_schema(candidate, evidence=evidence)
            if candidate.obligation.level.value == "mandatory":
                required.append(candidate.attribute)

        extension_regions = sorted(extension_regions_by_entity.get(entity, set()))
        if extension_regions:
            properties["extensions"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    region: {"$ref": f"./extensions/{region}/{entity}Extension.json"}
                    for region in extension_regions
                },
            }

        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": entity_schema_id(domain, version, entity),
            "title": entity,
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
        }
        if required:
            schema["required"] = sorted(required)
        schemas[entity] = schema
    return schemas


def build_extension_schemas(
    candidates: list[C8Canonicalcandidate],
    *,
    domain: str,
    version: str,
    owners: Mapping[str, str] | None = None,
    evidence_by_candidate: Mapping[str, list[str]] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Section 11.2's worked shape: one extension namespace schema per
    (region, entity), carrying x-owner/x-rationale governance annotations
    and, per property, x-placementRule/x-weight/x-evidence."""
    owners = owners or {}
    evidence_by_candidate = evidence_by_candidate or {}
    by_region_entity: dict[tuple[str, str], list[C8Canonicalcandidate]] = {}
    for candidate in candidates:
        placement = candidate.placement.value
        if placement == "core":
            continue
        region = placement.split(":", 1)[1]
        by_region_entity.setdefault((region, candidate.entity), []).append(candidate)

    schemas: dict[tuple[str, str], dict[str, Any]] = {}
    for (region, entity), group in by_region_entity.items():
        properties: dict[str, Any] = {}
        required: list[str] = []
        for candidate in group:
            evidence = evidence_by_candidate.get(str(candidate.candidateId), [])
            prop = _property_schema(candidate, evidence=evidence)
            prop["x-placementRule"] = candidate.placementRule
            prop["x-weight"] = int(candidate.weight)
            prop["x-evidence"] = evidence
            properties[candidate.attribute] = prop
            if candidate.obligation.level.value == "mandatory":
                required.append(candidate.attribute)

        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": extension_schema_id(domain, version, region, entity),
            "title": f"{region.upper()} {entity} extension",
            "x-owner": owners.get(region, f"Regional Architect, {region.upper()}"),
            "x-rationale": (
                f"Attributes required by {region.upper()} jurisdiction "
                "that have no counterpart in the other regions."
            ),
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = sorted(required)
        schemas[(region, entity)] = schema
    return schemas
