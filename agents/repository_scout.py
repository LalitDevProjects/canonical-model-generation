"""
Repository Scout (Section 4.2's pass-2 pseudocode: "the Repository Scout
agent reads headers, titles and descriptions only"). Explicitly deferred
to Increment 6 back at Increment 2 -
connectors/relevance.py::default_uncertain_policy's own docstring:
"no Repository Scout until Increment 6" - this module is that promise
kept.

No tool call is needed: the agent reads ArtefactRef.title/.description
directly, exactly as the spec's own one-line description says. tools=[]
on the agent itself is therefore correct, not an oversight.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from connectors.base import ArtefactRef
from connectors.relevance import ScoutVerdict
from substrate.api import SubstrateApi

from agents.base import Agent, RunContext, WorkItem
from agents.validation import Guardrail, Violation

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["uri", "in_domain", "reason"],
                "properties": {
                    "uri": {"type": "string"},
                    "in_domain": {"type": "boolean"},
                    "reason": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

_IMPERATIVE_OVERRIDE_RE = re.compile(
    r"\bignore\s+(all\s+|any\s+)?previous\s+instructions\b|\bdisregard\s+(all\s+|any\s+)?(previous|prior)\s+instructions\b",
    re.IGNORECASE,
)


def _guardrail_reason_not_injected(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G1: a code-level belt-and-braces check, not the primary control -
    the architectural controls are the [INJECTION] prompt block and
    Section 13.3's "no consequential actions" (a bad Scout verdict just
    means an item enters or skips pass 2's keep list, nothing
    irreversible). A verdict whose OWN reason parrots override language
    is strong evidence the model reproduced injected text rather than
    reasoning about the artefact - reject it outright rather than trust
    a verdict built on it."""
    violations: list[Violation] = []
    for verdict in output.get("verdicts", []):
        reason = verdict.get("reason", "")
        if _IMPERATIVE_OVERRIDE_RE.search(reason):
            violations.append(Violation(
                level="V4", code="G1-injection-echo",
                detail=f"verdict reason for {verdict.get('uri')!r} echoes override language: {reason!r}",
                record_id=verdict.get("uri"),
            ))
    return violations


def _guardrail_in_domain_needs_a_real_reason(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G2: in_domain=true without a concrete cited signal is exactly the
    "confident prose is not evidence" failure mode this repo's own
    Adversarial Critic guardrail (Section 7.5.4) warns about elsewhere -
    applied here at the one-guardrail-per-verdict granularity, not the
    whole-response one."""
    violations: list[Violation] = []
    for verdict in output.get("verdicts", []):
        if verdict.get("in_domain") is True and not verdict.get("reason", "").strip():
            violations.append(Violation(
                level="V4", code="G2-empty-reason",
                detail=f"in_domain=true for {verdict.get('uri')!r} with no reason given",
                record_id=verdict.get("uri"),
            ))
    return violations


class RepositoryScoutAgent(Agent):
    agent_id = "repository-scout"
    family = "discovery"
    output_schema = OUTPUT_SCHEMA
    prompt_template = "repository-scout"
    tools: list[str] = []
    model_tier = "fast"
    guardrails = [
        Guardrail(id="G1", description="verdict reasons must not echo injected override language", check=_guardrail_reason_not_injected),
        Guardrail(id="G2", description="in_domain=true requires a non-empty reason", check=_guardrail_in_domain_needs_a_real_reason),
    ]

    def __init__(self) -> None:
        self._expected_uris: frozenset[str] = frozenset()

    def assemble_context(self, item: WorkItem, api: SubstrateApi) -> dict[str, Any]:
        """Deterministic: the artefact list is sorted by uri before
        rendering, so the same uncertain batch always produces the same
        prompt, same order, regardless of connector/discover() iteration
        order.

        Also records the input uri set as per-invocation instance state,
        read back by validate_semantics() below - the Agent ABC's own
        validate_semantics(output, ctx) signature (Section 7.1) has no
        `item` parameter, so this is how an agent that needs to check its
        output against its own input (an anti-drop check) can do so;
        assemble_context and validate_semantics run on the same instance
        within one invoke() call, including across its own retries."""
        self._expected_uris = frozenset(str(a["uri"]) for a in item.payload["artefacts"])
        artefacts = sorted(item.payload["artefacts"], key=lambda a: str(a["uri"]))
        return {"domain": item.payload["domain"], "artefacts": artefacts}

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """Anti-drop: every input uri must get exactly one verdict back -
        a model that silently omits an artefact would otherwise let it
        fall through pass 2 unclassified."""
        returned_uris = [v.get("uri") for v in output.get("verdicts", [])]
        violations: list[Violation] = []
        if len(returned_uris) != len(set(returned_uris)):
            violations.append(Violation(level="V2", code="duplicate-verdict", detail="a uri received more than one verdict"))
        missing = self._expected_uris - set(returned_uris)
        for uri in sorted(missing):
            violations.append(Violation(level="V2", code="dropped-artefact", detail=f"no verdict returned for {uri!r}", record_id=uri))
        return violations


def _work_item_for(uncertain: list[ArtefactRef], domain: str) -> WorkItem:
    item_id = "scout-" + "-".join(sorted(ref.uri for ref in uncertain))[:120]
    artefacts = [
        {"uri": ref.uri, "title": ref.title or "", "description": ref.description or ""}
        for ref in uncertain
    ]
    return WorkItem(item_id=item_id, stage="S1", kind="scout-batch", payload={"artefacts": artefacts, "domain": domain})


def make_repository_scout_classifier(
    ctx: RunContext, *, agent: RepositoryScoutAgent | None = None,
) -> Callable[[list[ArtefactRef], str], Iterator[tuple[ArtefactRef, ScoutVerdict]]]:
    """The real scout_agent.classify(...) - a factory, not a bare
    function, because filter_relevance's own `scout_classifier` parameter
    signature (connectors/relevance.py) takes exactly
    `(uncertain: list[ArtefactRef], domain: str)`, with no way to thread
    a RunContext through it - unlike the Increment 2 interim placeholder
    (default_uncertain_policy), a real agent invocation genuinely needs
    one (the model gateway, budget, tools, substrate). The returned
    closure matches filter_relevance's expected signature exactly, so
    `filter_relevance(refs, domain, cfg, scout_classifier=make_repository_scout_classifier(ctx))`
    is the real replacement call site - connectors/relevance.py itself
    needs zero changes."""
    scout = agent or RepositoryScoutAgent()

    def _classify(uncertain: list[ArtefactRef], domain: str) -> Iterator[tuple[ArtefactRef, ScoutVerdict]]:
        if not uncertain:
            return
        item = _work_item_for(uncertain, domain)
        result = scout.invoke(item, ctx)

        verdicts_by_uri = {v["uri"]: v for v in result.output["verdicts"]}
        for ref in uncertain:
            verdict = verdicts_by_uri[ref.uri]
            yield ref, ScoutVerdict(in_domain=bool(verdict["in_domain"]), reason=str(verdict["reason"]))

    return _classify
