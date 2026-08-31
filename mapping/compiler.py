"""
Section 10.4's `compile_spec()`, transcribed against this repo's real C10
MappingSpec/C5 AttributeRecord shapes, plus one builder-added static check
(D1) needed because `mapping/interpreter.py::Plan.reverse()` had to be
designed from scratch (see that module's docstring).

The spec's own pseudocode takes `canonical: CanonicalModel` and calls
`canonical.type_of(e.canonical)` - no such type is defined anywhere in
this repo (no C-contract represents "the canonical model" as a queryable
object; the closest real data is a set of ratified C8 CanonicalCandidate
records). `canonical_types` here is the minimal projection T3 actually
needs: a plain `{canonicalPath: dataType}` mapping, built by the caller
from whatever candidates are in hand (golden fixtures, an agent's own
work items, an acceptance test). When an entry's canonical path isn't in
that mapping, T3 is skipped for it rather than treated as a failure - T3
checks type *drift* against a known canonical type, it is not a totality
check (that's T1's job, and the gap register's, elsewhere).

T4's "value map is not injective" check (Section 10.3's own valueMap row:
"Reverse fails if the map is not injective; the compiler checks this") is
folded into this same pass rather than given its own letter, since it is
a completeness property of the same valueMaps section T4 already reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C10.MappingSpec._1_0 import C10Mappingspec, ValueMaps
from mapping.interpreter import DEFAULT_ON_FAILURE, Plan, Step
from mapping.parser import MappingParseError, TransformCall, parse_transform_expr
from mapping.transforms import TRANSFORMS

_STATIC_OUTPUT_TYPE: dict[str, str] = {
    "formatDate": "string",
    "instantAtStartOfDay": "dateTime",
    "valueMap": "string",
    "toMonetaryAmount": "MonetaryAmount",
    "toIdentifier": "Identifier",
    "decompose": "object",
    "compose": "string",
    "concat": "string",
    "scale": "decimal",
    "normaliseCase": "string",
}

_WIDENING_PAIRS = {
    ("date", "dateTime"),
    ("integer", "decimal"),
    ("decimal", "integer"),
    ("MonetaryAmount", "object"),
    ("Identifier", "object"),
}

_CRITICAL_WEIGHT = 5
_SILENT_FAILURES = {"skip", "default"}


@dataclass(frozen=True)
class CompileError:
    check: str
    path: str
    message: str


class CompilationFailed(Exception):
    def __init__(self, errors: list[CompileError]) -> None:
        summary = errors[0].message if errors else "compile failed"
        super().__init__(f"{len(errors)} compile error(s), first: {summary}")
        self.errors = errors


def infer_output_type(chain: list[TransformCall], source_type: str | None) -> str | None:
    current = source_type
    for call in chain:
        if call.name == "parseDate":
            current = "dateTime" if "zone" in call.args else "date"
        elif call.name in ("identity", "coalesce"):
            continue
        elif call.name == "constant":
            current = None
        elif call.name in _STATIC_OUTPUT_TYPE:
            current = _STATIC_OUTPUT_TYPE[call.name]
    return current


def type_compatible(produced: str | None, expected: str) -> bool:
    if produced is None or produced == expected:
        return True
    return (produced, expected) in _WIDENING_PAIRS


def compile_spec(
    spec: C10Mappingspec,
    region_ir: list[C5Attributerecord],
    canonical_types: Mapping[str, str],
) -> Plan:
    errors: list[CompileError] = []
    region_by_path = {rec.path: rec for rec in region_ir}
    covered = {e.region for e in spec.mappings if e.region}

    # T1 Totality
    for rec in region_ir:
        if rec.path not in covered:
            errors.append(CompileError("T1", rec.path, "no mapping entry"))

    parsed_chains: dict[int, list[TransformCall]] = {}
    for index, e in enumerate(spec.mappings):
        if e.disposition is not None or not e.transform:
            continue
        try:
            parsed_chains[index] = parse_transform_expr(e.transform)
        except MappingParseError as err:
            errors.append(CompileError("PARSE", e.canonical or "", str(err)))

    for index, e in enumerate(spec.mappings):
        if e.disposition is not None:
            continue
        chain = parsed_chains.get(index)
        if chain is None:
            continue

        # T2 Weight rule
        if e.weight is not None and int(e.weight) >= _CRITICAL_WEIGHT:
            on_failure = e.onFailure.value if e.onFailure else DEFAULT_ON_FAILURE
            if on_failure in _SILENT_FAILURES:
                errors.append(
                    CompileError("T2", e.canonical or "", "weight>=5 requires reject or escalate")
                )

        # T3 Type fit
        source_rec = region_by_path.get(e.region) if e.region else None
        source_type = source_rec.dataType.value if source_rec else None
        expected = canonical_types.get(e.canonical) if e.canonical else None
        if expected is not None:
            produced = infer_output_type(chain, source_type)
            if not type_compatible(produced, expected):
                errors.append(
                    CompileError("T3", e.canonical or "", f"{produced} cannot satisfy {expected}")
                )

        # T4 Value-map completeness + injectivity
        for call in chain:
            if call.name != "valueMap":
                continue
            map_id = call.args.get("map")
            vm = (spec.valueMaps or {}).get(map_id) if map_id else None
            if vm is None:
                errors.append(CompileError("T4", e.canonical or "", f"unknown value map {map_id!r}"))
                continue
            declared_values = {
                item.value for item in (source_rec.enumeration or [])
            } if source_rec else set()
            missing = declared_values - set(vm.mappings)
            if missing and vm.unmappedValues is None:
                errors.append(
                    CompileError("T4", e.canonical or "", f"unmapped values: {sorted(missing)}")
                )
            if spec.header.direction == "bidirectional":
                if len(set(vm.mappings.values())) != len(vm.mappings):
                    errors.append(
                        CompileError(
                            "T4", e.canonical or "", f"value map {map_id!r} is not injective, cannot reverse"
                        )
                    )

        # D1 (builder addition) - Section 10.3's own "Reverse is undefined"
        # rule for coalesce/constant means a bidirectional entry using
        # either at the top level has no working reverse() step.
        if spec.header.direction == "bidirectional":
            non_reversible = [c.name for c in chain if TRANSFORMS[c.name].reverse is None]
            if non_reversible:
                errors.append(
                    CompileError(
                        "D1",
                        e.canonical or "",
                        f"{non_reversible[0]} has no reverse; not permitted in a bidirectional spec",
                    )
                )

    if errors:
        raise CompilationFailed(errors)

    return _build_plan(spec, parsed_chains)


def _build_plan(spec: C10Mappingspec, parsed_chains: dict[int, list[TransformCall]]) -> Plan:
    steps: list[Step] = []
    value_maps = spec.valueMaps or {}
    for index, e in enumerate(spec.mappings):
        weight = int(e.weight) if e.weight is not None else 0

        if e.disposition is not None:
            steps.append(
                Step(
                    canonical_path=None,
                    region_path=e.region,
                    transform_chain=(),
                    disposition_status=e.disposition.status.value,
                    on_failure=DEFAULT_ON_FAILURE,
                    weight=weight,
                    reversible=False,
                    declared_loss_kind=None,
                    note=e.note,
                )
            )
            continue

        chain = _resolve_value_maps(parsed_chains[index], value_maps)
        reversible = all(TRANSFORMS[c.name].reverse is not None for c in chain)
        if not reversible:
            loss_kind: str | None = "undefined-reverse"
        elif any(TRANSFORMS[c.name].lossy for c in chain) and e.note:
            loss_kind = "precision"
        else:
            loss_kind = None

        steps.append(
            Step(
                canonical_path=e.canonical,
                region_path=e.region,
                transform_chain=tuple(chain),
                disposition_status=None,
                on_failure=e.onFailure.value if e.onFailure else DEFAULT_ON_FAILURE,
                weight=weight,
                reversible=reversible,
                declared_loss_kind=loss_kind,
                note=e.note,
            )
        )
    return Plan(steps=tuple(steps))


def _resolve_value_maps(chain: list[TransformCall], value_maps: Mapping[str, ValueMaps]) -> list[TransformCall]:
    resolved: list[TransformCall] = []
    for call in chain:
        if call.name != "valueMap":
            resolved.append(call)
            continue
        vm = value_maps[call.args["map"]]
        args = dict(call.args)
        args["resolved_map"] = dict(vm.mappings)
        args["unmapped_values"] = vm.unmappedValues.value if vm.unmappedValues else "escalate"
        resolved.append(TransformCall(name=call.name, args=args))
    return resolved
