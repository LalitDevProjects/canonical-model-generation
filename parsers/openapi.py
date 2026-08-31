"""
OpenAPI / JSON Schema parser (Section 4.3; Section 2.3 tech-stack row:
"Parsing - OpenAPI | openapi-spec-validator plus a custom resolver | Full
$ref resolution including remote and circular references" - I3 scope is
narrower: local, in-document $ref recording (as a reference dataType with
typeDetail.refTarget), not full remote/circular resolution, since nothing
in the golden corpus or this increment's acceptance test requires it).

Walks components.schemas.* recursively (real recursion, unlike the
archived pre-rebuild connector, which only walked one level deep for
OpenAPI) plus per-operation path parameters not otherwise reachable from
components.schemas.

oneOf/anyOf/discriminator composition is deliberately NOT given
choice-like polymorphism treatment here (a documented Increment 3 scope
decision) - only plain object/array/scalar/$ref shapes are walked.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

import yaml

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.common.defs import DataType

from parsers.type_normalisation import from_openapi
from parsers.record_builder import build_record

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}


def _pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _cardinality_for(is_required: bool, is_array: bool) -> str:
    if is_array:
        return "1..n" if is_required else "0..n"
    return "1..1" if is_required else "0..1"


def parse_openapi(content: bytes, source_artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    document = yaml.safe_load(content)
    records: list[C5Attributerecord] = []

    schemas = ((document.get("components") or {}).get("schemas")) or {}
    for schema_name, schema_node in schemas.items():
        records.extend(_walk(
            node=schema_node,
            path=schema_name,
            parent_path=None,
            pointer=f"/components/schemas/{_pointer_escape(schema_name)}",
            is_required=True,
            source_artefact=source_artefact,
            run_id=run_id,
            emit_self=False,
        ))

    for path_key, path_item in (document.get("paths") or {}).items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId") or f"{method}_{path_key}"
            for index, param in enumerate(operation.get("parameters") or []):
                param_schema = param.get("schema")
                if param_schema is None:
                    continue
                records.extend(_walk(
                    node=param_schema,
                    path=f"{operation_id}.{param['name']}",
                    parent_path=None,
                    pointer=f"/paths/{_pointer_escape(path_key)}/{method}/parameters/{index}/schema",
                    is_required=bool(param.get("required", False)),
                    source_artefact=source_artefact,
                    run_id=run_id,
                    emit_self=True,
                ))

    return records


def _walk(
    *,
    node: dict[str, Any],
    path: str,
    parent_path: str | None,
    pointer: str,
    is_required: bool,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    emit_self: bool,
) -> list[C5Attributerecord]:
    """emit_self=False for a top-level components.schemas entry, whose
    properties get their own records but which itself isn't an
    "attribute" of anything - True everywhere else (a path parameter, or
    any nested property/array-item)."""
    records: list[C5Attributerecord] = []

    if "$ref" in node:
        if emit_self:
            records.append(_build(
                node, path, parent_path, pointer, is_required, source_artefact, run_id,
                data_type=DataType.reference,
                type_detail={"refTarget": node["$ref"]},
            ))
        return records

    json_type = node.get("type")

    if json_type == "object" and "properties" in node:
        if emit_self:
            records.append(_build(
                node, path, parent_path, pointer, is_required, source_artefact, run_id,
                data_type=DataType.object, type_detail={},
            ))
        required_names = set(node.get("required") or [])
        for prop_name, prop_node in node["properties"].items():
            records.extend(_walk(
                node=prop_node,
                path=f"{path}.{prop_name}",
                parent_path=path,
                pointer=f"{pointer}/properties/{_pointer_escape(prop_name)}",
                is_required=prop_name in required_names,
                source_artefact=source_artefact,
                run_id=run_id,
                emit_self=True,
            ))
        return records

    if json_type == "array":
        items_node = node.get("items") or {}
        records.extend(_walk(
            node=items_node,
            path=path,
            parent_path=parent_path,
            pointer=f"{pointer}/items",
            is_required=is_required,
            source_artefact=source_artefact,
            run_id=run_id,
            emit_self=True,
        ))
        # Re-tag the just-emitted record for this path as array-cardinality,
        # since the item walk above emitted it with scalar cardinality.
        if records and records[-1].path == path:
            last = records[-1]
            records[-1] = last.model_copy(update={
                "cardinality": _cardinality_for(is_required, is_array=True),
            })
        return records

    if emit_self:
        normalised = from_openapi(json_type, node.get("format"))
        records.append(_build(
            node, path, parent_path, pointer, is_required, source_artefact, run_id,
            data_type=normalised.data_type, type_detail=dict(normalised.type_detail),
        ))
    return records


def _build(
    node: dict[str, Any],
    path: str,
    parent_path: str | None,
    pointer: str,
    is_required: bool,
    source_artefact: C1Sourceartefact,
    run_id: UUID,
    data_type: DataType,
    type_detail: dict[str, Any],
) -> C5Attributerecord:
    local_name = path.rsplit(".", 1)[-1]
    return build_record(
        source_artefact=source_artefact,
        run_id=run_id,
        path=path,
        local_name=local_name,
        parent_path=parent_path,
        data_type=data_type,
        type_detail=type_detail,
        cardinality=_cardinality_for(is_required, is_array=False),
        obligation_level="mandatory" if is_required else "optional",
        description=node.get("description"),
        enumeration_values=list(node.get("enum") or []),
        constraints=_constraints_from(node),
        locator=pointer,
    )


def _constraints_from(node: dict[str, Any]) -> list[tuple[str, str]]:
    constraints: list[tuple[str, str]] = []
    if "minLength" in node:
        constraints.append(("length", f"minLength={node['minLength']}"))
    if "maxLength" in node:
        constraints.append(("length", f"maxLength={node['maxLength']}"))
    if "pattern" in node:
        constraints.append(("pattern", node["pattern"]))
    if "minimum" in node:
        constraints.append(("range", f"minimum={node['minimum']}"))
    if "maximum" in node:
        constraints.append(("range", f"maximum={node['maximum']}"))
    return constraints
