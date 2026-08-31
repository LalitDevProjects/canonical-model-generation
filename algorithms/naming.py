"""
Naming conventions (Section 9.9 - "Core Algorithms"). check_name() is the
convention checker Canonical Synthesiser's own guardrail G2 enforces:
"Naming MUST satisfy the convention checker (9.9). Violations are
rejected before persistence, not corrected silently."

"Violations reject the candidate before persistence rather than being
auto-corrected, because a silently renamed attribute breaks the
rationale the SME will read."

check_name()'s own NamingViolation (kind, message) is a distinct, local
shape - the spec's own pseudocode constructs it as `Violation("case",
"...")`, a plain 2-field object, not agents.validation.Violation's
4-field (level/code/detail/record_id) framework shape. Canonical
Synthesiser's own G2 guardrail adapts between the two; this module
stays a pure Section 9 algorithm with no dependency on agents/.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from algorithms.profiling import MONETARY_TOKENS, canonical_tokens

ALLOWED_ABBREVIATIONS = frozenset({"id", "ref", "uri", "iso"})

IDENTIFIER_TOKENS = frozenset({"id", "identifier", "code", "number", "ref"})
"""Provisional heuristic for ctx.denotes_identifier, the same
pattern-matching status as algorithms.profiling.looks_temporal/
looks_monetary - not spec-defined, a builder decision."""

_ATTRIBUTE_CASE_RE = re.compile(r"[a-z][a-zA-Z0-9]*")
_ENTITY_CASE_RE = re.compile(r"[A-Z][a-zA-Z0-9]*")
_REGION_MARKERS = ("us", "uk", "eu")


@dataclass(frozen=True)
class NamingViolation:
    kind: str
    message: str


@dataclass(frozen=True)
class NamingContext:
    """Everything check_name() needs beyond the raw entity/attribute
    strings. is_core: from the candidate's own (deterministically
    corrected) placement. data_type/type_name: the synthesised
    attribute's own dataType and canonical type name. offset_required:
    from the synthesised attribute's typeDetail.offsetRequired.
    denotes_money/denotes_identifier: token-set heuristics, see
    looks_denotes_money()/looks_denotes_identifier() below."""

    is_core: bool
    data_type: str
    type_name: str
    offset_required: bool
    denotes_money: bool
    denotes_identifier: bool


def looks_denotes_money(tokens: tuple[str, ...]) -> bool:
    return bool(set(tokens) & MONETARY_TOKENS)


def looks_denotes_identifier(tokens: tuple[str, ...]) -> bool:
    return bool(set(tokens) & IDENTIFIER_TOKENS)


def check_name(
    entity: str,
    attribute: str,
    ctx: NamingContext,
    *,
    abbreviations: Mapping[str, str],
) -> list[NamingViolation]:
    """Section 9.9's check_name(), verbatim. abbreviations is the same
    config.settings.ClusteringConfig.abbreviations dict Increment 7's
    blocking already reuses - one abbreviation dictionary, not a second
    one. canonical_tokens(attribute) is called with NO abbreviations
    kwarg (unlike blocking's own usage): this check needs to see whether
    a RAW abbreviated token (e.g. "amt") is still present in the name,
    which an expansion-applying call would hide."""
    v: list[NamingViolation] = []
    if not _ATTRIBUTE_CASE_RE.fullmatch(attribute):
        v.append(NamingViolation("case", "attributes MUST be lowerCamelCase"))
    if not _ENTITY_CASE_RE.fullmatch(entity):
        v.append(NamingViolation("case", "entities MUST be PascalCase"))
    for tok in canonical_tokens(attribute):
        if tok in abbreviations and tok not in ALLOWED_ABBREVIATIONS:
            v.append(NamingViolation("abbreviation", f"expand {tok!r}"))
    # A crude substring check, transcribed literally - "status" contains
    # "us", for instance. Left as-is rather than "fixed": Section 9.5's
    # own homonym signals are explicitly "intentionally trigger-happy,"
    # and a false-positive here costs a human a moment's reconsideration,
    # not a silently wrong canonical name - the same asymmetry the spec
    # defends elsewhere.
    if any(r in attribute.lower() for r in _REGION_MARKERS) and ctx.is_core:
        v.append(NamingViolation("region-marker", "core names MUST NOT encode a region"))
    if ctx.data_type == "boolean" and not attribute.startswith(("is", "has")):
        v.append(NamingViolation("boolean", "booleans MUST be positively phrased is*/has*"))
    if ctx.denotes_money and ctx.type_name != "MonetaryAmount":
        v.append(NamingViolation("money", "monetary values MUST use MonetaryAmount"))
    if ctx.denotes_identifier and ctx.type_name != "Identifier":
        v.append(NamingViolation("identifier", "identifiers MUST use Identifier"))
    if ctx.data_type == "dateTime" and not ctx.offset_required:
        v.append(NamingViolation("datetime", "instants MUST require an offset"))
    return v
