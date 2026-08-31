"""
Section 10.3's closed transform library, transcribed as real Python.

The spec's own framing - "Adding a transform is a governed change requiring
a signature, a reverse definition and property tests - deliberate friction"
- argues for this living as code, not config/platform.yaml data (unlike
ClusteringConfig/CoverageConfig's tunable weights): extending the
vocabulary should require a code review, not a YAML edit.

Every forward/reverse function shares one signature: (value, **kwargs) ->
Any. `value` is the input the interpreter's step loop threads through the
chain (mapping/interpreter.py::Plan.forward/reverse); `kwargs` are exactly
the TransformCall's own parsed args (mapping/parser.py), reused unchanged
in both directions - so a reverse function receives the *same* arguments
the forward call was given (e.g. parseDate's reverse receives `fmt` and
drops the `zone` it doesn't need), never a second, independently-authored
argument list. This keeps mapping/interpreter.py::Plan.reverse() fully
generic: TRANSFORMS[name].reverse(value, **call.args) is the entire
dispatch, symmetric with forward.

Five of the spec's own "Reverse" column entries (formatDate's counterpart
"parseDate", instantAtStartOfDay's "toLocalDate", valueMap's
"valueMapInverse", toMonetaryAmount's "amountOf", toIdentifier's
"valueOf", concat's "split") are never themselves legal `transform:` line
names in the spec's own 14-row table - they only ever appear in the
Reverse column. They are implemented here as private functions, not
registered under their own TRANSFORMS key: an SME cannot write
`transform: valueOf(...)` in a mapping spec, only the interpreter invokes
them internally when undoing a step.

Two transforms have an undefined reverse (`coalesce`, `constant` used as
an entry's own top-level transform - "Permitted only with direction:
toCanonical" / "n/a"): `TransformSpec.reverse` is None for both.
`constant` used as a *nested argument value* (e.g. Appendix C's
`toMonetaryAmount(currency=constant("GBP"))`) is a different thing
entirely - mapping/parser.py resolves that to a plain literal at parse
time, never invoking this module's `constant` transform at all.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

TransformFn = Callable[..., Any]

# LDML-style date pattern tokens (yyyy/MM/dd/HH/mm/ss), matching Appendix
# C's own worked example (`parseDate(fmt="yyyy-MM-dd")`) and Section 10's
# general SME-readability goal. The spec never states which pattern
# language fmt uses; Python's strptime directives are not SME-facing, so
# this module translates the spec's own LDML-style literal tokens into
# strptime directives rather than exposing %Y/%m/%d to mapping authors.
# Longest-first, and case matters (MM=month, mm=minute) - alternation in
# a single regex evaluates left-to-right per match position, so ordering
# here is significant.
_LDML_TOKENS = re.compile(r"yyyy|yy|MM|dd|HH|mm|ss")
_LDML_TO_STRPTIME = {
    "yyyy": "%Y",
    "yy": "%y",
    "MM": "%m",
    "dd": "%d",
    "HH": "%H",
    "mm": "%M",
    "ss": "%S",
}


class TransformError(Exception):
    """Raised when a transform cannot produce a value for its given input."""


@dataclass(frozen=True)
class TransformSpec:
    name: str
    signature: str
    forward: TransformFn
    reverse: TransformFn | None
    reverse_name: str | None
    lossy: bool
    notes: str


def _ldml_to_strptime(fmt: str) -> str:
    return _LDML_TOKENS.sub(lambda m: _LDML_TO_STRPTIME[m.group(0)], fmt)


# --- identity ----------------------------------------------------------


def _identity(value: Any, **_: Any) -> Any:
    return value


# --- parseDate / formatDate ---------------------------------------------


def _parse_date(value: Any, *, fmt: str, zone: str | None = None, **_: Any) -> date | datetime:
    if not isinstance(value, str):
        raise TransformError(f"parseDate: expected a string, got {type(value).__name__}")
    try:
        parsed = datetime.strptime(value, _ldml_to_strptime(fmt))
    except ValueError as err:
        raise TransformError(f"parseDate: {err}") from err
    if zone is None:
        return parsed.date()
    return parsed.replace(tzinfo=ZoneInfo(zone))


def _format_date(value: Any, *, fmt: str, **_: Any) -> str:
    if not isinstance(value, date | datetime):
        raise TransformError(f"formatDate: expected a date/dateTime, got {type(value).__name__}")
    return value.strftime(_ldml_to_strptime(fmt))


def _parse_date_reverse(value: Any, *, fmt: str, zone: str | None = None, **_: Any) -> str:
    return _format_date(value, fmt=fmt)


def _format_date_reverse(value: Any, *, fmt: str, **_: Any) -> date | datetime:
    return _parse_date(value, fmt=fmt)


# --- instantAtStartOfDay / toLocalDate ----------------------------------


def _instant_at_start_of_day(value: Any, *, zone: str, **_: Any) -> datetime:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TransformError(f"instantAtStartOfDay: expected a date, got {type(value).__name__}")
    return datetime(value.year, value.month, value.day, tzinfo=ZoneInfo(zone))


def _to_local_date(value: Any, *, zone: str, **_: Any) -> date:
    if not isinstance(value, datetime):
        raise TransformError(f"toLocalDate: expected a dateTime, got {type(value).__name__}")
    localised = value.astimezone(ZoneInfo(zone)) if value.tzinfo is not None else value
    return localised.date()


# --- valueMap / valueMapInverse -----------------------------------------
#
# `resolved_map` and `unmapped_values` are not authored by the SME in the
# mapping spec's own `transform:` line (which only ever names
# `map: <id>`) - mapping/compiler.py::compile_spec() resolves the named
# `map` against the spec's own `valueMaps` section during T4 and injects
# the resolved dict/policy into the compiled TransformCall's args, so the
# interpreter stays a pure `TRANSFORMS[name].forward(value, **call.args)`
# dispatch with no special-casing per transform.


def _value_map(
    value: Any,
    *,
    map: str,
    resolved_map: dict[str, str],
    unmapped_values: str = "escalate",
    **_: Any,
) -> str:
    if not isinstance(value, str):
        raise TransformError(f"valueMap: expected a string, got {type(value).__name__}")
    if value in resolved_map:
        return resolved_map[value]
    if unmapped_values == "passthrough":
        return value
    raise TransformError(f"valueMap: {value!r} has no entry in {map!r}")


def _value_map_inverse(
    value: Any,
    *,
    map: str,
    resolved_map: dict[str, str],
    unmapped_values: str = "escalate",
    **_: Any,
) -> str:
    inverse = {target: source for source, target in resolved_map.items()}
    if not isinstance(value, str):
        raise TransformError(f"valueMap: expected a string, got {type(value).__name__}")
    if value in inverse:
        return inverse[value]
    if unmapped_values == "passthrough":
        return value
    raise TransformError(f"valueMap: {value!r} has no reverse entry in {map!r}")


# --- toMonetaryAmount / amountOf ----------------------------------------


def _to_monetary_amount(value: Any, *, currency: str, **_: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            amount: float = float(value)
        except ValueError as err:
            raise TransformError(f"toMonetaryAmount: {err}") from err
    elif isinstance(value, int | float):
        amount = float(value)
    else:
        raise TransformError(f"toMonetaryAmount: expected number|string, got {type(value).__name__}")
    return {"amount": amount, "currency": currency}


def _amount_of(value: Any, *, currency: str, **_: Any) -> float:
    if not isinstance(value, dict) or "amount" not in value:
        raise TransformError("amountOf: expected a MonetaryAmount object")
    return float(value["amount"])


# --- toIdentifier / valueOf ----------------------------------------------


def _to_identifier(value: Any, *, scheme: str, issuer: str, **_: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TransformError(f"toIdentifier: expected a string, got {type(value).__name__}")
    return {"value": value, "scheme": scheme, "issuer": issuer}


def _value_of(value: Any, *, scheme: str, issuer: str, **_: Any) -> str:
    if not isinstance(value, dict) or "value" not in value:
        raise TransformError("valueOf: expected an Identifier object")
    identifier_value: str = value["value"]
    return identifier_value


# --- decompose / compose --------------------------------------------------
#
# "pattern is a named, tested rule" (Section 10.3) - the spec gives no
# concrete pattern language. Resolved here as a Python regex with named
# capture groups for `pattern`, and a Python str.format template for
# `template` - both stdlib, both directly testable, and both required on
# every decompose/compose entry (not just the direction actually used) so
# the interpreter can reverse the step: the spec gives no worked
# decompose/compose example to resolve this against otherwise.


def _decompose(value: Any, *, pattern: str, template: str | None = None, **_: Any) -> dict[str, str]:
    if not isinstance(value, str):
        raise TransformError(f"decompose: expected a string, got {type(value).__name__}")
    match = re.fullmatch(pattern, value)
    if match is None:
        raise TransformError(f"decompose: {value!r} does not match pattern {pattern!r}")
    return match.groupdict()


def _compose(value: Any, *, template: str, pattern: str | None = None, **_: Any) -> str:
    if not isinstance(value, dict):
        raise TransformError(f"compose: expected an object, got {type(value).__name__}")
    try:
        return template.format(**value)
    except KeyError as err:
        raise TransformError(f"compose: template {template!r} needs field {err}") from err


def _decompose_reverse(value: Any, *, pattern: str, template: str | None = None, **_: Any) -> str:
    if template is None:
        raise TransformError("decompose: no template given to reverse this step")
    return _compose(value, template=template)


def _compose_reverse(value: Any, *, template: str, pattern: str | None = None, **_: Any) -> dict[str, str]:
    if pattern is None:
        raise TransformError("compose: no pattern given to reverse this step")
    return _decompose(value, pattern=pattern)


# --- concat / split --------------------------------------------------------


def _concat(value: Any, *, separator: str, **_: Any) -> str:
    if not isinstance(value, list):
        raise TransformError(f"concat: expected a list, got {type(value).__name__}")
    return separator.join(str(v) for v in value)


def _split(value: Any, *, separator: str, **_: Any) -> list[str]:
    if not isinstance(value, str):
        raise TransformError(f"split: expected a string, got {type(value).__name__}")
    return value.split(separator)


# --- coalesce ---------------------------------------------------------------
#
# Signature `[T] -> T`, but the grammar gives one `region:` path per
# entry, not several - there is no worked coalesce example in the spec to
# resolve a multi-path design against. This reference interpreter reads
# `[T]` from a single region_path that itself points at an array-shaped
# source (e.g. a list of candidate values already assembled upstream),
# not multiple independent region paths.


def _coalesce(value: Any, **_: Any) -> Any:
    if not isinstance(value, list):
        raise TransformError(f"coalesce: expected a list, got {type(value).__name__}")
    for candidate in value:
        if candidate is not None:
            return candidate
    raise TransformError("coalesce: every candidate was null")


# --- constant -----------------------------------------------------------
#
# Appendix C writes `constant("GBP")` as a bare positional literal, not
# `constant(value="GBP")` - the only positional-argument transform call in
# the spec's own worked example. mapping/parser.py normalises that single
# positional argument to the `const` kwarg name (chosen to avoid colliding
# with the `value` parameter every transform receives positionally for its
# piped-in input).


def _constant(value: Any, *, const: Any, **_: Any) -> Any:
    return const


# --- scale ----------------------------------------------------------------


def _scale(value: Any, *, factor: float, **_: Any) -> float:
    if not isinstance(value, int | float):
        raise TransformError(f"scale: expected a number, got {type(value).__name__}")
    return float(value) * factor


def _scale_reverse(value: Any, *, factor: float, **_: Any) -> float:
    if factor == 0:
        raise TransformError("scale: cannot reverse a zero factor")
    return _scale(value, factor=1 / factor)


# --- normaliseCase ----------------------------------------------------------

_CASE_MODES: dict[str, Callable[[str], str]] = {
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
}


def _normalise_case(value: Any, *, mode: str, **_: Any) -> str:
    if not isinstance(value, str):
        raise TransformError(f"normaliseCase: expected a string, got {type(value).__name__}")
    if mode not in _CASE_MODES:
        raise TransformError(f"normaliseCase: unknown mode {mode!r}")
    return _CASE_MODES[mode](value)


TRANSFORMS: dict[str, TransformSpec] = {
    "identity": TransformSpec(
        name="identity",
        signature="T -> T",
        forward=_identity,
        reverse=_identity,
        reverse_name="identity",
        lossy=False,
        notes="The commonest case by a wide margin.",
    ),
    "parseDate": TransformSpec(
        name="parseDate",
        signature="string, fmt, zone? -> date|dateTime",
        forward=_parse_date,
        reverse=_parse_date_reverse,
        reverse_name="formatDate",
        lossy=True,
        notes="Reverse is lossy where the source had no time component; the loss is declared.",
    ),
    "formatDate": TransformSpec(
        name="formatDate",
        signature="date|dateTime, fmt -> string",
        forward=_format_date,
        reverse=_format_date_reverse,
        reverse_name="parseDate",
        lossy=False,
        notes="",
    ),
    "instantAtStartOfDay": TransformSpec(
        name="instantAtStartOfDay",
        signature="date, zone -> dateTime",
        forward=_instant_at_start_of_day,
        reverse=_to_local_date,
        reverse_name="toLocalDate",
        lossy=True,
        notes="Declared precision loss on reverse.",
    ),
    "valueMap": TransformSpec(
        name="valueMap",
        signature="string, mapId -> string",
        forward=_value_map,
        reverse=_value_map_inverse,
        reverse_name="valueMapInverse",
        lossy=False,
        notes="Reverse fails if the map is not injective; the compiler checks this.",
    ),
    "toMonetaryAmount": TransformSpec(
        name="toMonetaryAmount",
        signature="number|string, currency -> MonetaryAmount",
        forward=_to_monetary_amount,
        reverse=_amount_of,
        reverse_name="amountOf",
        lossy=False,
        notes="Currency may be a literal, a sibling path or a constant per region.",
    ),
    "toIdentifier": TransformSpec(
        name="toIdentifier",
        signature="string, scheme, issuer -> Identifier",
        forward=_to_identifier,
        reverse=_value_of,
        reverse_name="valueOf",
        lossy=False,
        notes="",
    ),
    "decompose": TransformSpec(
        name="decompose",
        signature="string, pattern -> object",
        forward=_decompose,
        reverse=_decompose_reverse,
        reverse_name="compose",
        lossy=False,
        notes="Address and name splitting; pattern is a named, tested rule.",
    ),
    "compose": TransformSpec(
        name="compose",
        signature="object, template -> string",
        forward=_compose,
        reverse=_compose_reverse,
        reverse_name="decompose",
        lossy=False,
        notes="",
    ),
    "concat": TransformSpec(
        name="concat",
        signature="[string], separator -> string",
        forward=_concat,
        reverse=_split,
        reverse_name="split",
        lossy=False,
        notes="Reverse requires an unambiguous separator; checked statically.",
    ),
    "coalesce": TransformSpec(
        name="coalesce",
        signature="[T] -> T",
        forward=_coalesce,
        reverse=None,
        reverse_name=None,
        lossy=False,
        notes="Reverse is undefined. Permitted only with direction: toCanonical.",
    ),
    "constant": TransformSpec(
        name="constant",
        signature="-> T",
        forward=_constant,
        reverse=None,
        reverse_name=None,
        lossy=False,
        notes="For canonical attributes a region cannot supply. MUST carry a note.",
    ),
    "scale": TransformSpec(
        name="scale",
        signature="number, factor -> number",
        forward=_scale,
        reverse=_scale_reverse,
        reverse_name="scale(1/factor)",
        lossy=False,
        notes="Units, minor-to-major currency units.",
    ),
    "normaliseCase": TransformSpec(
        name="normaliseCase",
        signature="string, mode -> string",
        forward=_normalise_case,
        reverse=_identity,
        reverse_name="identity",
        lossy=True,
        notes="Reverse is lossy and declared as such.",
    ),
}
