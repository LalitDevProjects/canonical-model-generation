"""
Type normalisation (Section 4.3): "The normalisation table below is
authoritative and MUST be implemented as a lookup, not as ad hoc
conditionals scattered through the parsers, because the coverage
denominator depends on two regions using the same normalised type for the
same concept."

Boundary with algorithms/profiling.py, reconciled (the spec states two
rules that look like they overlap - they don't, once split by which pass
enforces them):

- "unknown... Always raises a finding; never silently defaults to string"
  splits into two independent halves. THIS module enforces the "never
  silently defaults" half structurally: no lookup here ever falls through
  to DataType.string for an unrecognised source type - the fallback is
  always DataType.unknown. The "raises a finding" half belongs entirely to
  the profiler, which independently raises an opaque-type finding whenever
  it sees dataType == unknown (see algorithms/profiling.py's profile()).
  This module has no dependency on algorithms/ at all.

- "Monetary values MUST normalise here, never to a float" is enforced
  structurally too, not by name-based detection: DataType has no
  float/number member. OpenAPI `number` and XSD `xs:decimal` map only to
  DataType.decimal, unconditionally - there is no numeric-name sniffing at
  this layer. (The profiler's separate looks_monetary heuristic is an
  independent safety net for the case a source mistakenly declares a
  monetary field as `string` instead of `number`/`decimal` - a different
  problem, in a different pass.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from generated.common.defs import DataType


class TypeDetailFragment(TypedDict, total=False):
    bits: int
    offsetRequired: bool
    refTarget: str


def _empty_type_detail() -> TypeDetailFragment:
    return TypeDetailFragment()


@dataclass(frozen=True)
class NormalisedType:
    data_type: DataType
    type_detail: TypeDetailFragment = field(default_factory=_empty_type_detail)


# --- OpenAPI / JSON Schema -------------------------------------------------
# key: (json_schema_type, format) -> NormalisedType. format=None matches
# "no format given"; a (type, None) fallback is tried when a specific
# format isn't found, before falling back to unknown.
_OPENAPI_TABLE: dict[tuple[str, str | None], NormalisedType] = {
    ("string", None): NormalisedType(DataType.string),
    ("string", "date"): NormalisedType(DataType.date),
    ("string", "date-time"): NormalisedType(DataType.dateTime, {"offsetRequired": True}),
    ("string", "byte"): NormalisedType(DataType.binary),
    ("integer", None): NormalisedType(DataType.integer, {"bits": 64}),
    ("integer", "int32"): NormalisedType(DataType.integer, {"bits": 32}),
    ("integer", "int64"): NormalisedType(DataType.integer, {"bits": 64}),
    ("number", None): NormalisedType(DataType.decimal),
    ("number", "double"): NormalisedType(DataType.decimal),
    ("number", "float"): NormalisedType(DataType.decimal),
    ("boolean", None): NormalisedType(DataType.boolean),
    ("object", None): NormalisedType(DataType.object),
    ("array", None): NormalisedType(DataType.array),
}


def from_openapi(json_type: str | None, fmt: str | None) -> NormalisedType:
    """json_type=None covers OpenAPI/JSON Schema's "no type declared" row
    of the spec's table - always DataType.unknown, never a silent
    default."""
    if json_type is None:
        return NormalisedType(DataType.unknown)
    hit = _OPENAPI_TABLE.get((json_type, fmt))
    if hit is not None:
        return hit
    hit = _OPENAPI_TABLE.get((json_type, None))
    if hit is not None:
        return hit
    return NormalisedType(DataType.unknown)


# --- XSD --------------------------------------------------------------
# Only base-type QNames. Structural idioms (complex type, element ref,
# maxOccurs>1, xs:choice) are handled by parsers/xsd.py itself before this
# lookup is ever consulted - they aren't a base-type string to look up.
_XSD_TABLE: dict[str, NormalisedType] = {
    "xs:string": NormalisedType(DataType.string),
    "xs:token": NormalisedType(DataType.string),
    "xs:int": NormalisedType(DataType.integer, {"bits": 32}),
    "xs:long": NormalisedType(DataType.integer, {"bits": 64}),
    "xs:integer": NormalisedType(DataType.integer, {"bits": 64}),
    "xs:decimal": NormalisedType(DataType.decimal),
    "xs:boolean": NormalisedType(DataType.boolean),
    "xs:date": NormalisedType(DataType.date),
    "xs:dateTime": NormalisedType(DataType.dateTime, {"offsetRequired": False}),
    "xs:base64Binary": NormalisedType(DataType.binary),
    "xs:IDREF": NormalisedType(DataType.reference),
    "xs:anyType": NormalisedType(DataType.unknown),
    # Not in the spec's own 11-row table, but real XSD idioms with an
    # existing, exact DataType enum member from Increment 1 - mapping
    # them there is strictly better than falling back to unknown for
    # something this unambiguous. Judgment call, flagged.
    "xs:time": NormalisedType(DataType.time),
    "xs:duration": NormalisedType(DataType.duration),
}


def from_xsd_qname(qname: str) -> NormalisedType:
    return _XSD_TABLE.get(qname, NormalisedType(DataType.unknown))


# --- Avro ---------------------------------------------------------------
_AVRO_TABLE: dict[str, NormalisedType] = {
    "string": NormalisedType(DataType.string),
    "int": NormalisedType(DataType.integer, {"bits": 32}),
    "long": NormalisedType(DataType.integer, {"bits": 64}),
    "boolean": NormalisedType(DataType.boolean),
    "bytes": NormalisedType(DataType.binary),
    "record": NormalisedType(DataType.object),
    "array": NormalisedType(DataType.array),
}

_AVRO_LOGICAL_TABLE: dict[str, NormalisedType] = {
    "decimal": NormalisedType(DataType.decimal),
    "date": NormalisedType(DataType.date),
    "timestamp-millis": NormalisedType(DataType.dateTime, {"offsetRequired": False}),
    "timestamp-micros": NormalisedType(DataType.dateTime, {"offsetRequired": False}),
}


def from_avro(avro_type: object, logical_type: str | None) -> NormalisedType:
    """avro_type is typed `object` because Avro fields legitimately carry
    either a bare type name (str) or a union (list) - a union with no
    single dominant branch always normalises to unknown, per the spec's
    own table note ("union with no dominant branch")."""
    if logical_type is not None and logical_type in _AVRO_LOGICAL_TABLE:
        return _AVRO_LOGICAL_TABLE[logical_type]
    if isinstance(avro_type, list):
        return NormalisedType(DataType.unknown)
    if isinstance(avro_type, str):
        return _AVRO_TABLE.get(avro_type, NormalisedType(DataType.unknown))
    return NormalisedType(DataType.unknown)
