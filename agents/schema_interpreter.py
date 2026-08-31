"""
Schema Interpreter (Section 3.2's contract-relationship table: "C5
AttributeRecord ... parser-svc and Schema Interpreter"; Section 7.7:
"Deterministic parsing. No model call at all - this is the largest
single cost saving in the platform"). A thin Agent-ABC wrapper around
the already-real parsers/router.py::parse, reached through the
spec.parse tool (not called directly) - so the SAME authorisation/audit
path a model-calling agent's tool use would go through also covers
deterministic agents, not a special case.
"""

from __future__ import annotations

from typing import Any

from agents.base import RunContext, WorkItem
from agents.deterministic import DeterministicAgent
from agents.validation import Guardrail, Violation, validate_reference

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["attributes"],
    "properties": {
        "attributes": {"type": "array", "items": {"type": "object"}},
    },
    "additionalProperties": False,
}
"""`items` is deliberately loose ({"type": "object"}), not a $ref to
contracts/C5/AttributeRecord/1.0.json: the real, full C5 shape is already
enforced upstream by parsers/router.py::parse's own Pydantic model
construction (a malformed record raises there, before compute() can even
return it) - re-validating the complete C5 contract a second time here,
via a $ref this generic validate_schema() has no registry to resolve,
would be redundant ceremony, not real additional safety."""


def _guardrail_every_record_has_evidence(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G1: "restated for the model... enforced in code" (Section 7.4) -
    parsers/record_builder.py already guarantees every C5Attributerecord
    it builds carries exactly one evidenceRef, so this is expected to
    never actually fire; kept as the same belt-and-braces discipline
    Repository Scout's own guardrails use, not because the parser is
    known to be unreliable."""
    violations: list[Violation] = []
    for record in output.get("attributes", []):
        if not record.get("evidenceRefs"):
            violations.append(Violation(
                level="V4", code="G1-missing-evidence",
                detail=f"{record.get('attributeId')!r} has no evidenceRefs",
                record_id=record.get("attributeId"),
            ))
    return violations


class SchemaInterpreterAgent(DeterministicAgent):
    agent_id = "schema-interpreter"
    family = "comprehension"
    output_schema = OUTPUT_SCHEMA
    prompt_template = ""  # unused: model_tier is n/a, DeterministicAgent.invoke() never calls render()
    tools: list[str] = ["spec.parse"]
    guardrails = [
        Guardrail(id="G1", description="every returned record has a non-empty evidenceRefs", check=_guardrail_every_record_has_evidence),
    ]

    def __init__(self) -> None:
        self._current_artefact_id: str | None = None

    def compute(self, item: WorkItem, ctx: RunContext) -> dict[str, Any]:
        artefact_id = str(item.payload["artefactId"])
        self._current_artefact_id = artefact_id
        result = ctx.tools.call(
            self.agent_id, "spec.parse",
            {"artefactId": artefact_id, "format": str(item.payload.get("format", ""))},
            ctx.run_id,
        )
        assert isinstance(result, list)
        return {"attributes": result}

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """V2: every returned record's evidenceRefs must resolve to the
        one artefact this invocation actually parsed - a record citing
        evidence from a DIFFERENT artefact would mean the parser (or a
        future non-deterministic replacement) attributed evidence
        incorrectly."""
        if self._current_artefact_id is None:
            return []
        known_ids = {self._current_artefact_id}
        violations: list[Violation] = []
        for record in output.get("attributes", []):
            refs = [str(r) for r in record.get("evidenceRefs", [])]
            violations.extend(validate_reference(refs, known_ids))
        return violations
