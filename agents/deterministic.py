"""
Deterministic agents (model_tier: n/a - Section 7.7: "Deterministic
parsing. No model call at all - this is the largest single cost saving
in the platform"). No prompt, no model_gateway call, no retry loop: a
pure function either produces valid output or it doesn't, and retrying a
pure function against the same input produces the same result, so
Section 7.6's retry table simply doesn't apply here - there is nothing
retrying would change.

Resolves Schema Interpreter's (and, in later increments, Extension
Partitioner's/Coverage Scorer's) `model_tier: n/a`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from agents.base import Agent, AgentResult, ModelTier, RunContext, WorkItem
from agents.validation import (
    GuardrailViolation,
    SchemaValidationFailed,
    WorkItemFailed,
    evaluate,
    validate_schema,
)
from substrate.api import SubstrateApi


class DeterministicAgent(Agent):
    model_tier: ModelTier = "n/a"

    @abstractmethod
    def compute(self, item: WorkItem, ctx: RunContext) -> dict[str, Any]:
        """Replaces the prompt-render + model-call steps of Agent.invoke()
        for a deterministic agent - the real work (e.g. a parser call via
        a tool) happens here instead."""
        raise NotImplementedError

    def assemble_context(self, item: WorkItem, api: SubstrateApi) -> dict[str, Any]:
        """Deterministic agents have no prompt to assemble context for -
        the abstract method is satisfied trivially so DeterministicAgent
        remains a concrete Agent subclass without forcing every subclass
        to re-implement a no-op."""
        return {}

    def invoke(self, item: WorkItem, ctx: RunContext) -> AgentResult:
        raw = self.compute(item, ctx)
        try:
            output = validate_schema(raw, self.output_schema)
        except SchemaValidationFailed as exc:
            raise WorkItemFailed(f"deterministic agent produced schema-invalid output: {exc.detail}") from exc

        semantic_violations = self.validate_semantics(output, ctx)
        if semantic_violations:
            raise WorkItemFailed("semantic validation failed (deterministic agent, no retry)", semantic_violations)

        guardrail_violations = evaluate(self.guardrails, output, ctx)
        if guardrail_violations:
            raise GuardrailViolation(guardrail_violations)

        ctx.tools.write(self.agent_id, ctx.run_id, output)
        return AgentResult(agent_id=self.agent_id, work_item_id=item.item_id, output=output, outcome="ok")
