"""
Avro parser (Section 2.3 tech-stack table: "Parsing - Avro | fastavro
schema API | Corroborating evidence only in wave 1"). Deliberately thin,
per that spec's own framing and the confirmed decision to use the stdlib
json module rather than fastavro: an .avsc file is itself JSON, and this
increment only needs to walk its field structure, not validate real data
records against it (fastavro's actual strength, and out of scope here).

No Avro-specific idiom handling beyond record (nested walk), array
(cardinality 0..n, recurse into items), and logical types (decimal/date/
timestamp-* via parsers/type_normalisation.py) - none is required by the
spec, which names zero Avro-specific idioms anywhere (unlike XSD's four
named idioms).

Every field is treated as unconditionally mandatory/1..1: Avro's schema
level has no obligation/cardinality concept comparable to XSD's minOccurs
or OpenAPI's required list (nullability is expressed only via a union
type, e.g. ["null", "string"], which - consistent with
type_normalisation.from_avro's own "union with no dominant branch, always
unknown" rule - is not given special optional/nullable treatment here
either; a documented simplification appropriate to Avro's thin,
corroborating-evidence scope).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.common.defs import DataType

from parsers.record_builder import build_record
from parsers.type_normalisation import from_avro


def parse_avro(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    schema = json.loads(content)
    root_name = schema.get("name", "root")
    return _walk_record(schema, path_prefix=root_name, source_artefact=source_artefact, run_id=run_id)


def _walk_record(
    record_schema: dict[str, Any],
    *,
    path_prefix: str,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
) -> list[C5Attributerecord]:
    records: list[C5Attributerecord] = []
    for field in record_schema.get("fields", []):
        records.extend(_walk_field(
            field,
            path=f"{path_prefix}.{field['name']}",
            parent_path=path_prefix,
            source_artefact=source_artefact,
            run_id=run_id,
        ))
    return records


def _walk_field(
    field: dict[str, Any],
    *,
    path: str,
    parent_path: str,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
) -> list[C5Attributerecord]:
    field_type = field["type"]
    local_name = field["name"]
    description = field.get("doc")

    if isinstance(field_type, dict):
        if field_type.get("type") == "record":
            self_record = build_record(
                source_artefact=source_artefact, run_id=run_id, path=path, local_name=local_name,
                parent_path=parent_path, data_type=DataType.object, type_detail={},
                cardinality="1..1", obligation_level="mandatory",
                locator=f"#{path}", description=description,
            )
            return [self_record, *_walk_record(field_type, path_prefix=path, source_artefact=source_artefact, run_id=run_id)]

        if field_type.get("type") == "array":
            items = field_type.get("items")
            inner = _walk_field(
                {"name": local_name, "type": items, "doc": description},
                path=path, parent_path=parent_path, source_artefact=source_artefact, run_id=run_id,
            )
            if inner:
                inner[0] = inner[0].model_copy(update={"cardinality": "0..n"})
            return inner

        normalised = from_avro(field_type.get("type"), field_type.get("logicalType"))
        return [build_record(
            source_artefact=source_artefact, run_id=run_id, path=path, local_name=local_name,
            parent_path=parent_path, data_type=normalised.data_type, type_detail=dict(normalised.type_detail),
            cardinality="1..1", obligation_level="mandatory",
            locator=f"#{path}", description=description,
        )]

    normalised = from_avro(field_type, None)
    return [build_record(
        source_artefact=source_artefact, run_id=run_id, path=path, local_name=local_name,
        parent_path=parent_path, data_type=normalised.data_type, type_detail=dict(normalised.type_detail),
        cardinality="1..1", obligation_level="mandatory",
        locator=f"#{path}", description=description,
    )]
