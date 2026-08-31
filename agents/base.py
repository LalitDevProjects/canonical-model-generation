"""
The Agent base contract (Section 7.1): "Every agent invocation follows
the same ten-step path. Each arrow ... is an enforcement point, not a
data hand-off: the design assumes model output is untrusted until it has
passed schema validation, semantic validation and the agent's own
guardrails ... guardrail evaluation happens in Python, not in the
prompt."

Shapes not given by the spec (WorkItem's own field list, RunContext,
AgentResult) are builder decisions sized to what this repo's actual two
Increment 6 agents (Repository Scout, Schema Interpreter) and the
validation ladder need - the same status as
ArtefactRef/ConnectorScope/HealthStatus at Increment 2 ("referenced in
the spec's pseudocode but never defined there"). Violation/Guardrail and
the ladder's own exception types live in agents/validation.py, not here
- that's the lower layer this module builds on, avoiding a circular
import (a Guardrail's own check callback needs a RunContext, which is
defined here).

No S1-S8 orchestrator exists at Increment 6 (Section 8.3's own
pseudocode is an AWS Step Functions definition this repo has no way to
run, and no increment's acceptance test through I9 requires a real
orchestrator) - `route()` is an identity stub, invoking one agent
against one work item directly in Python.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from referencing import Registry

from generated.C11.RunManifest._1_0 import Pins

from agents.model_gateway import Budget, ModelGateway
from agents.prompt_render import PROMPTS_ROOT, render
from agents.validation import (
    Guardrail,
    GuardrailViolation,
    SchemaValidationFailed,
    Violation,
    WorkItemFailed,
    evaluate,
    validate_schema,
)
from substrate.api import SubstrateApi
from tools.gateway import ToolGateway

Family = Literal["discovery", "comprehension", "synthesis", "assurance"]
ModelTier = Literal["fast", "high", "n/a"]


@dataclass(frozen=True)
class WorkItem:
    """One unit of fan-out (Section 8.2's own granularity per stage - a
    source-system x region for S1, a whole uncertain-batch for Repository
    Scout, a single artefact for Schema Interpreter, etc). item_id is
    caller-assigned and deterministic (never a random UUID, matching
    this repo's identity philosophy throughout), so the same corpus
    produces the same work items across independent runs."""

    item_id: str
    stage: str
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    agent_id: str
    work_item_id: str
    output: dict[str, Any]
    outcome: Literal["ok", "retry", "escalated", "failed"]


@dataclass(frozen=True)
class RunContext:
    """Everything an Agent.invoke() call needs, assembled by the caller
    (never constructed by the agent itself) - matches this repo's
    explicit-dependency style throughout (gate/gate.py::classify_and_redact,
    substrate/ingest.py::ingest_artefacts)."""

    run_id: UUID
    substrate: SubstrateApi
    pins: Pins
    model_gateway: ModelGateway
    budget: Budget
    tools: ToolGateway


def route(output: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Identity stub (Section 8's own state machine is out of scope this
    increment - see this module's docstring). A real orchestrator would
    dispatch `output` onward to the next stage; here it is simply
    returned, so `Agent.invoke()`'s own return value is exactly what a
    caller passed in for step 9's write."""
    return output


class Agent(ABC):
    agent_id: str
    family: Family
    output_schema: dict[str, Any]
    prompt_template: str
    """Template id (a directory name under prompts/), not a version -
    the version is resolved via ctx.pins.prompts[self.agent_id],
    matching Section 7.1's own "version pinned in RunManifest" framing."""
    tools: list[str]
    model_tier: ModelTier
    guardrails: list[Guardrail]
    prompt_root: Path = PROMPTS_ROOT
    """Overridable per-subclass (never per-instance state) so tests can
    point a fake Agent at a tmp_path template without writing test-only
    fixture content into the real prompts/ directory - the same
    "constructor/class-attribute override, not monkeypatching" pattern
    every store in this repo already uses for its own root path
    (pipeline/run_store.py::RunStore's base_path, etc)."""
    schema_registry: Registry | None = None
    """Increment 7: set when output_schema has external $refs (e.g.
    Semantic Resolver's contracts/C6/ConceptCluster/1.0.json, which $refs
    into common/defs.json) - passed through to validate_schema's own
    optional registry kwarg. None (the default) preserves Increment 6's
    two agents' exact behaviour, whose output_schema dicts have no
    external $ref at all."""

    @abstractmethod
    def assemble_context(self, item: WorkItem, api: SubstrateApi) -> dict[str, Any]:
        """Deterministic. Same work item + same corpus -> same context, same order."""
        raise NotImplementedError

    @abstractmethod
    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """Beyond JSON Schema: evidence resolvability, manifest
        membership, enumeration provenance, agent-specific invariants."""
        raise NotImplementedError

    def invoke(self, item: WorkItem, ctx: RunContext) -> AgentResult:
        """The ten-step path (Section 7.1), with Section 7.6's retry
        table driving a real retry loop: a schema-validation failure
        (V1) re-renders the prompt with the validation error appended,
        up to 2 retries; a semantic-validation failure re-renders with
        the offending values named, 1 retry; a guardrail violation (V4)
        gets 0 retries and escalates immediately - "retrying a guardrail
        breach trains nothing and wastes budget." Third schema failure
        and any semantic failure past its single retry both fail the
        work item (WorkItemFailed) - Section 7.6: "the tempting fix ...
        is to drop it and keep the attribute. That silently converts an
        evidenced attribute into an unevidenced one" - escalating,
        not repairing, is the point of this whole ladder."""
        context = self.assemble_context(item, ctx.substrate)

        schema_retries_left = 2
        semantic_retries_left = 1
        correction_note: str | None = None

        while True:
            prompt_version = ctx.pins.prompts.get(self.agent_id, "1.0.0")
            prompt = render(
                self.prompt_template, prompt_version, context,
                output_schema=self.output_schema, correction_note=correction_note, root=self.prompt_root,
            )
            budget_slice = ctx.budget.slice_for(item.stage)
            raw = ctx.model_gateway.call(
                self.model_tier, prompt, response_schema=self.output_schema, budget=budget_slice,
            )

            try:
                output = validate_schema(raw, self.output_schema, registry=self.schema_registry)
            except SchemaValidationFailed as exc:
                if schema_retries_left > 0:
                    schema_retries_left -= 1
                    correction_note = f"Your previous output failed schema validation: {exc.detail}. Correct it and try again."
                    continue
                raise WorkItemFailed(f"schema validation failed after retries: {exc.detail}") from exc

            semantic_violations = self.validate_semantics(output, ctx)
            if semantic_violations:
                if semantic_retries_left > 0:
                    semantic_retries_left -= 1
                    named = "; ".join(f"{v.code}: {v.detail}" for v in semantic_violations)
                    correction_note = f"The following values were rejected: {named}. Correct them and try again."
                    continue
                raise WorkItemFailed("semantic validation failed after retry", semantic_violations)

            guardrail_violations = evaluate(self.guardrails, output, ctx)
            if guardrail_violations:
                raise GuardrailViolation(guardrail_violations)

            ctx.tools.write(self.agent_id, ctx.run_id, output)
            routed = route(output, ctx)
            return AgentResult(agent_id=self.agent_id, work_item_id=item.item_id, output=routed, outcome="ok")
