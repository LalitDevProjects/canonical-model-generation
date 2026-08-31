"""
The validation ladder (Section 7.3): five levels, each an enforcement
point outside the model. "The design assumes model output is untrusted
until it has passed schema validation, semantic validation and the
agent's own guardrails."

| Level | Check | On failure |
|---|---|---|
| V1 Schema | Output validates against agent.output_schema | Retry up to 2 times with the validation error appended to the prompt |
| V2 Reference | Every evref resolves and its artefact is in CorpusManifest (I1) | Retry once; then escalate. Never repair by dropping the reference |
| V3 Provenance | Every enumeration value traces to a source enumeration, or is explicitly marked canonical-addition | Retry once with the offending values named |
| V4 Guardrail | Agent-specific rules from its specification | No retry. Escalate to the human queue with the violation recorded |
| V5 Cross-artefact | Invariants I2-I5 across the run's artefact set | Fail the work item and raise a finding; the stage exit criterion is not met |

The exception types and Violation/Guardrail dataclasses live here, not in
agents/base.py, specifically so agents/base.py can import this module
without a cycle: Agent.invoke() (base.py) calls these functions, and a
Guardrail's own `check` callback needs a RunContext (defined in
base.py) - resolved via a TYPE_CHECKING-only import below, never a real
runtime dependency in this direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import jsonschema
from jsonschema.exceptions import best_match
from referencing import Registry

from contracts.validators import (
    InvariantViolation,
    artefact_id_from_evref,
    check_i2_cluster_members_same_run,
    check_i3_candidate_traces_to_attribute,
    check_i4_coverage_scored_attributes_evidenced,
    check_i5_mapping_entries_have_disposition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agents.base import RunContext


@dataclass(frozen=True)
class Violation:
    """One failure at one validation-ladder level, attributable to one
    record - the same shape as contracts/validators.py's
    InvariantViolation, deliberately: both describe "one check failed for
    one record," just at different layers (cross-artefact invariants vs.
    an agent's own output)."""

    level: Literal["V1", "V2", "V3", "V4", "V5"]
    code: str
    detail: str
    record_id: str | None = None


@dataclass(frozen=True)
class Guardrail:
    """Agent-specific rules from its own specification (Section 7.5),
    evaluated in Python - "these are advisory to the model and enforced
    in code, the code is authoritative" (Section 7.4)."""

    id: str
    description: str
    check: Callable[[dict[str, Any], "RunContext"], list[Violation]]


class SchemaValidationFailed(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class GuardrailViolation(Exception):
    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(f"{len(violations)} guardrail violation(s): {[v.code for v in violations]}")
        self.violations = violations


class WorkItemFailed(Exception):
    """Terminal: retries exhausted (Section 7.6's "third failure fails
    the work item"), or a V5 cross-artefact-invariant breach."""

    def __init__(self, detail: str, violations: list[Violation] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.violations = violations or []


def validate_schema(raw: dict[str, Any], schema: dict[str, Any], *, registry: Registry | None = None) -> dict[str, Any]:
    """V1. jsonschema.Draft202012Validator - the same validator class
    contracts/validators.py's own module docstring requires everywhere
    else in this repo. registry is optional (Increment 6's two agents'
    output_schema dicts have no external $ref, so it defaults to None and
    their behaviour is unchanged) - Increment 7's Semantic Resolver
    points output_schema at the real contracts/C6/ConceptCluster/1.0.json,
    which $refs into common/defs.json, and needs a real registry to
    resolve those refs (jsonschema.Draft202012Validator(schema) alone
    would raise Unresolvable on the first $ref it hit)."""
    validator_kwargs: dict[str, Any] = {"registry": registry} if registry is not None else {}
    validator = jsonschema.Draft202012Validator(schema, **validator_kwargs)
    errors = list(validator.iter_errors(raw))
    if errors:
        worst = best_match(errors)
        detail = worst.message if worst is not None else "; ".join(e.message for e in errors)
        raise SchemaValidationFailed(detail)
    return raw


def validate_reference(evidence_refs: list[str], known_artefact_ids: set[str]) -> list[Violation]:
    """V2: "Every evref resolves and its artefact is in CorpusManifest."
    Reuses contracts/validators.py::artefact_id_from_evref directly - the
    same evref-parsing logic I1 already uses, not reimplemented."""
    violations: list[Violation] = []
    for ref in evidence_refs:
        artefact_id = artefact_id_from_evref(ref)
        if artefact_id is None or artefact_id not in known_artefact_ids:
            violations.append(Violation(
                level="V2", code="unresolvable-reference",
                detail=f"evidenceRef {ref!r} does not resolve to any artefact in the CorpusManifest",
                record_id=ref,
            ))
    return violations


def validate_provenance(output: dict[str, Any]) -> list[Violation]:
    """V3: "Every enumeration value traces to a source enumeration, or is
    explicitly marked canonical-addition." Returns [] unconditionally at
    Increment 6 - neither Repository Scout nor Schema Interpreter invents
    enumeration values (Schema Interpreter copies enumerations verbatim
    from the source schema; Repository Scout emits no enumerations at
    all) - documented as trivially-satisfied for these two agents, not
    unimplemented. A future agent that DOES synthesise enumeration
    values (e.g. Canonical Synthesiser, Increment 8) needs a real check
    here."""
    return []


def evaluate(guardrails: list[Guardrail], output: dict[str, Any], ctx: "RunContext") -> list[Violation]:
    """V4: runs every guardrail, in order, collecting all violations
    rather than stopping at the first - "the ladder runs to completion"
    is already this repo's convention for the L0-L4 sanitisation ladder
    (gate/detectors.py); the same discipline applies here."""
    violations: list[Violation] = []
    for guardrail in guardrails:
        violations.extend(guardrail.check(output, ctx))
    return violations


def validate_cross_artefact(kind: Literal["I2", "I3", "I4", "I5"], *args: Any) -> list[InvariantViolation]:
    """V5: "Invariants I2-I5 across the run's artefact set." A thin
    dispatcher onto the already-real cross-artefact invariant checks
    (contracts/validators.py) - never reimplemented. Genuinely
    unexercised by either Increment 6 agent: neither produces
    ConceptCluster/CanonicalCandidate/CoverageReport/MappingSpec data,
    none of which exist before Increments 7-9 - a real scope boundary,
    not a gap."""
    checks: dict[str, Callable[..., list[InvariantViolation]]] = {
        "I2": check_i2_cluster_members_same_run,
        "I3": check_i3_candidate_traces_to_attribute,
        "I4": check_i4_coverage_scored_attributes_evidenced,
        "I5": check_i5_mapping_entries_have_disposition,
    }
    return checks[kind](*args)
