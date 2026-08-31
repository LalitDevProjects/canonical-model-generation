"""
Attribute profiling (Section 9.1 - "Core Algorithms", not Section 4).
Landed at Increment 3 ahead of the rest of algorithms/ (blocking,
clustering - Increments 7-8) because I3's own acceptance test requires it
directly, the same way Increment 2 landed pipeline/run_store.py ahead of
pipeline/'s own named increment.

"Profiling runs after parsing and before clustering. It enriches each
AttributeRecord with the derived signals that clustering needs, and
raises findings where the declared contract looks wrong." "Findings are
surfaced to humans; they never mutate the recorded type" - this is the
other half of the parser/profiler separation whose first half lives in
parsers/type_normalisation.py: the parser records what the contract says,
this module records what it suspects, and the two are never conflated.

Finding and ProfiledAttribute are confirmed NOT persisted contracts (no
C1-C11 schema has a findings field; C5Attributerecord is
additionalProperties: false) - transient, in-pipeline structures that will
feed clustering once it exists (Increment 7).

canonical_tokens/head_noun/TYPE_FAMILY/looks_temporal/looks_monetary/
documented_values are all referenced by the spec's own profile() pseudocode
but never defined there - the versioned abbreviation dictionary Section 9.2
describes ("grows during the PoC... versioned as configuration, not code")
belongs to Increment 7's blocking work. What's implemented here is a
deliberately minimal, provisional heuristic sufficient for profile()'s own
needs now - simple token/keyword matching, not tuned further at this
increment.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.common.defs import DataType


@dataclass(frozen=True)
class Finding:
    kind: str
    message: str


@dataclass(frozen=True)
class ProfiledAttribute:
    record: C5Attributerecord
    tokens: tuple[str, ...]
    head_noun: str
    type_family: str
    parent_path: str | None
    sibling_names: tuple[str, ...]
    findings: tuple[Finding, ...]


TYPE_FAMILY: dict[DataType, str] = {
    DataType.string: "text",
    DataType.integer: "numeric",
    DataType.decimal: "numeric",
    DataType.boolean: "flag",
    DataType.date: "temporal",
    DataType.dateTime: "temporal",
    DataType.time: "temporal",
    DataType.duration: "temporal",
    DataType.binary: "opaque",
    DataType.object: "structural",
    DataType.array: "structural",
    DataType.reference: "structural",
    DataType.unknown: "opaque",
}
"""Provisional grouping, sufficient for profile()'s own return shape.
Increment 7's blocking work owns the richer, versioned notion of type
compatibility groups."""

_TOKEN_SPLIT_RE = re.compile(r"[_\-]|(?<=[a-z0-9])(?=[A-Z])")


def canonical_tokens(local_name: str) -> tuple[str, ...]:
    """Splits snake_case and camelCase local names into lowercase tokens,
    e.g. "lossDate" -> ("loss", "date"). Provisional: Section 9.2's
    versioned abbreviation dictionary (expanding e.g. "amt" -> "amount")
    is Increment 7 scope, not implemented here."""
    return tuple(t.lower() for t in _TOKEN_SPLIT_RE.split(local_name) if t)


def head_noun(tokens: tuple[str, ...]) -> str:
    """The last token is treated as the head noun (e.g. "lossDate" ->
    "date"), a common convention for right-headed compounds. Provisional -
    Increment 7 territory for anything more linguistically aware."""
    return tokens[-1] if tokens else ""


_TEMPORAL_TOKENS = {"date", "time", "timestamp", "at", "when", "occurred", "datetime"}
_MONETARY_TOKENS = {"amount", "reserve", "premium", "price", "cost", "fee", "value", "sum", "total"}
_NUMERIC_PATTERN_HINT = re.compile(r"\\d|\[0-9\]")


def looks_temporal(tokens: tuple[str, ...], description: str | None) -> bool:
    """Provisional heuristic: matches the spec's profile() signature
    exactly (tokens + description only - NOT observed values, even though
    Section 4.3's own prose separately mentions "name, description or
    observed enumeration" as informing type-suspicion in general; the
    §9.1 pseudocode's looks_temporal signature is narrower, and this
    follows the pseudocode literally)."""
    haystack = set(tokens) | set((description or "").lower().split())
    return bool(haystack & _TEMPORAL_TOKENS)


def looks_monetary(tokens: tuple[str, ...], description: str | None) -> bool:
    haystack = set(tokens) | set((description or "").lower().split())
    return bool(haystack & _MONETARY_TOKENS)


def _constraints_match_numeric_pattern(rec: C5Attributerecord) -> bool:
    """Pseudocode's rec.constraints_match(NUMERIC_PATTERN): true if any
    declared 'pattern' constraint's expression itself looks like a
    numeric-only regex (contains a digit class like \\d or [0-9])."""
    if not rec.constraints:
        return False
    return any(
        constraint.kind == "pattern" and bool(_NUMERIC_PATTERN_HINT.search(constraint.expression))
        for constraint in rec.constraints
    )


def documented_values(description: str | None) -> bool:
    """Provisional heuristic for "values documented but not declared":
    looks for common enumeration-announcing phrasing in free text."""
    if not description:
        return False
    return bool(re.search(r"\b(one of|values?:|either)\b", description, re.IGNORECASE))


def profile(rec: C5Attributerecord, siblings: Sequence[C5Attributerecord]) -> ProfiledAttribute:
    """Section 9.1's profile(), implemented directly against this repo's
    real generated C5Attributerecord shape (not the spec's abstracted
    pseudocode variable names). rec.semantics is itself optional on the
    real model - the spec's pseudocode implies unconditional access to
    rec.semantics.description, so a None-guard is added here that the
    pseudocode doesn't literally show."""
    tokens = canonical_tokens(rec.localName)
    findings: list[Finding] = []
    description = rec.semantics.description if rec.semantics else None

    if rec.dataType == DataType.string:
        if looks_temporal(tokens, description):
            findings.append(Finding("type-suspicion", "string that denotes a date"))
        if looks_monetary(tokens, description):
            findings.append(Finding("type-suspicion", "string that denotes an amount"))
        if _constraints_match_numeric_pattern(rec):
            findings.append(Finding("type-suspicion", "string constrained to numerics"))

    if rec.dataType == DataType.unknown:
        findings.append(Finding("opaque-type", "no type declared; requires confirmation"))

    if rec.dataType == DataType.string and not rec.enumeration and documented_values(description):
        findings.append(Finding("undeclared-enum", "values documented but not declared"))

    return ProfiledAttribute(
        record=rec,
        tokens=tokens,
        head_noun=head_noun(tokens),
        type_family=TYPE_FAMILY[rec.dataType],
        parent_path=rec.parentPath,
        sibling_names=tuple(sibling.localName for sibling in siblings),
        findings=tuple(findings),
    )
