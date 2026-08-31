"""Shared builders for mapping/ tests - real C5Attributerecord/C10Mappingspec
instances, not hand-rolled stand-ins, matching this repo's established
"validate against the real generated model" convention."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C10.MappingSpec._1_0 import C10Mappingspec

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")


def attribute_record(
    *,
    path: str,
    data_type: str = "string",
    region: str = "uk",
    obligation: str = "mandatory",
    enumeration: list[dict[str, Any]] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> C5Attributerecord:
    payload: dict[str, Any] = {
        "attributeId": f"attr://{region}/git-fixture/{path}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-fixture",
        "path": path,
        "localName": path.rsplit(".", 1)[-1],
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": obligation},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/fixture-artefact@{'a' * 16}#/{path}"],
    }
    if enumeration is not None:
        payload["enumeration"] = enumeration
    if constraints is not None:
        payload["constraints"] = constraints
    return C5Attributerecord.model_validate(payload)


def mapping_spec(
    *,
    direction: str = "toCanonical",
    mappings: list[dict[str, Any]],
    value_maps: dict[str, Any] | None = None,
) -> C10Mappingspec:
    payload: dict[str, Any] = {
        "header": {
            "mappingSpecId": "mapping-fixture",
            "canonicalRef": "canon://claims/1.0",
            "direction": direction,
            "generatedFrom": {
                "run": str(RUN_ID),
                "corpusManifest": "corpusmanifest-fixture",
                "agent": "mapping-generator/1.4.0",
            },
        },
        "mappings": mappings,
    }
    if value_maps is not None:
        payload["valueMaps"] = value_maps
    return C10Mappingspec.model_validate(payload)


def transform_entry(
    *,
    canonical: str,
    region: str,
    transform: str,
    weight: int = 3,
    on_failure: str = "escalate",
    obligation: str | None = None,
    note: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "canonical": canonical,
        "region": region,
        "transform": transform,
        "weight": weight,
        "onFailure": on_failure,
        "evidence": evidence or [f"evref://uk/git/fixture-artefact@{'a' * 16}#/{region}"],
    }
    if obligation is not None:
        entry["obligation"] = {"canonical": obligation, "region": obligation}
    if note is not None:
        entry["note"] = note
    return entry


def disposition_entry(
    *,
    region: str,
    status: str = "unmapped",
    reason: str = "No canonical counterpart.",
    weight: int = 1,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "canonical": None,
        "region": region,
        "disposition": {"status": status, "reason": reason},
        "weight": weight,
        "evidence": evidence or [f"evref://uk/git/fixture-artefact@{'a' * 16}#/{region}"],
    }
