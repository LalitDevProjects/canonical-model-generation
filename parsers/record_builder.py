"""
Shared C5Attributerecord construction, used by every parser
(openapi.py/xsd.py/wsdl.py/avro.py) so the identity/evidence conventions
established in Increments 1-2 are applied in exactly one place:

- attributeId = attr://{region}/{contractId}/{normalisedPath}, where
  contractId is the source artefact's own artefactId (deterministic, not
  a random UUID - matches this repo's identity philosophy throughout).
- evidenceRefs use the existing evref://{region}/{system}/{artefactId}@
  {contentHash}#{locator} scheme (contracts/common/defs.json), truncating
  contentHash to the 16 hex chars the evref pattern requires - the same
  convention already used in Increment 1/2 fixtures.
- evidenceTier is inherited directly from the source artefact (same
  evidence, same tier - no separate attribute-level tier logic exists
  anywhere in the spec).
- inferred=False always: parsers only run against declared/published
  contracts. The inferred=True path belongs exclusively to the
  out-of-scope Section 4.5 code-inference pipeline.
- confidence is left unset: its documented meaning is specifically about
  inference confidence scoring (Section 4.5), not parser certainty.

Callers pass plain strings for cardinality/obligation_level/constraint
kinds - this module does the enum construction (Cardinality(...),
Level(...), Kind(...)), the same division of responsibility
connectors/manifest.py already uses for Region(...)/System(...).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import (
    C5Attributerecord,
    Constraint,
    EnumerationItem,
    Kind,
    Semantics,
    Source,
    Source1,
    TypeDetail,
)
from generated.common.defs import Cardinality, DataType, EvidenceRef, Level, Obligation


def build_record(
    *,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    path: str,
    local_name: str,
    parent_path: str | None,
    data_type: DataType,
    type_detail: dict[str, Any],
    cardinality: str,
    obligation_level: str,
    locator: str,
    description: str | None = None,
    enumeration_values: Sequence[object] | None = None,
    constraints: Sequence[tuple[str, str]] | None = None,
    obligation_condition: str | None = None,
) -> C5Attributerecord:
    evref = (
        f"evref://{source_artefact.region.value}/{source_artefact.system.value}/"
        f"{source_artefact.artefactId}@{source_artefact.contentHash[:16]}#{locator}"
    )

    return C5Attributerecord(
        attributeId=f"attr://{source_artefact.region.value}/{source_artefact.artefactId}/{path}",
        runId=run_id,
        region=source_artefact.region,
        sourceContract=source_artefact.artefactId,
        path=path,
        localName=local_name,
        dataType=data_type,
        typeDetail=TypeDetail(**type_detail) if type_detail else None,
        cardinality=Cardinality(cardinality),
        obligation=Obligation(level=Level(obligation_level), condition=obligation_condition),
        enumeration=(
            [EnumerationItem(value=str(v), source=Source.declared) for v in enumeration_values]
            if enumeration_values
            else None
        ),
        constraints=(
            [Constraint(kind=Kind(kind), expression=expression, source=Source1.schema) for kind, expression in constraints]
            if constraints
            else None
        ),
        semantics=Semantics(description=description) if description else None,
        parentPath=parent_path,
        evidenceTier=source_artefact.evidenceTier,
        inferred=False,
        evidenceRefs=[EvidenceRef(root=evref)],
    )
