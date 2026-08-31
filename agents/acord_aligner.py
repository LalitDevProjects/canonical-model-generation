"""
ACORD Aligner (Section 7.5.2). Built in full spec fidelity - matching
Repository Scout/Schema Interpreter's own precedent of being built
completely even before every path could be exercised for real. But
ACORD Reference Architecture data has been permanently unavailable in
this repo since Increment 1 (unlicensed; SubstrateApi.acord_lookup
always returns []), so the agent's own guardrail G4 ("if licence
disposition != permitted, this agent MUST NOT run") means the real,
always-exercised pipeline path in this repo is Section 19.2's
deterministic degraded mode, not this agent. align_or_degrade() is the
top-level dispatcher; it never invokes this agent in this repo's own
configuration - G4 is enforced by never constructing a work item at all,
not by a runtime guardrail (there is nothing to guardrail-check in an
invocation that never happens).

G1 ("verdict=fit REQUIRES an acordRef returned by acord.lookup in this
invocation") is enforced via validate_semantics, not the V4 guardrail
list: Guardrail.check's signature (output, ctx) -> list[Violation] has
no access to the agent instance, only validate_semantics (a bound
method) does - the same framework constraint Repository Scout's
anti-drop check and Semantic Resolver's invented-member check already
work within. G3 ("a forced fit is prohibited") is inherently a semantic
judgment no structural check can fully verify; the weak, honestly-
documented proxy below is real but limited.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from referencing import Registry, Resource

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord

from contracts.validators import unwrap_ref
from substrate.api import SubstrateApi

from agents.base import Agent, RunContext, WorkItem
from agents.validation import Guardrail, Violation

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "contracts"


def _load_schema_registry() -> Registry:
    files = sorted(_CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text(encoding="utf-8")) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


SCHEMA_REGISTRY = _load_schema_registry()
OUTPUT_SCHEMA: dict[str, Any] = json.loads((_CONTRACTS_DIR / "C7" / "AlignmentRecord" / "1.0.json").read_text(encoding="utf-8"))

DEGRADED_MODE_RATIONALE = (
    "acord-aligner is disabled (licence disposition != permitted); ACORD "
    "alignment section left for SME completion (Section 19.2)."
)

_MISFIT_LANGUAGE = "no reasonable acord counterpart"


def _guardrail_g2_partial_requires_deviation(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G2: "verdict=partial REQUIRES a non-null deviation describing
    precisely how the syndicate usage differs.\""""
    if output.get("verdict") == "partial" and not str(output.get("deviation") or "").strip():
        return [Violation(level="V4", code="G2-missing-deviation", detail="verdict=partial with no deviation given")]
    return []


def _guardrail_g3_no_forced_fit(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G3: "A forced fit is prohibited: if the deviation changes what the
    attribute denotes, the verdict is misfit, not partial." Whether a
    deviation "changes what the attribute denotes" is a semantic
    judgment no structural check can fully verify - this is a real but
    honestly weak proxy: a partial verdict whose own deviation text
    echoes misfit language is a partial that should have been a
    misfit."""
    if output.get("verdict") == "partial" and _MISFIT_LANGUAGE in str(output.get("deviation") or "").lower():
        return [Violation(level="V4", code="G3-forced-fit", detail="deviation describes a total mismatch; verdict should be misfit, not partial")]
    return []


class AcordAlignerAgent(Agent):
    agent_id = "acord-aligner"
    family = "synthesis"
    output_schema = OUTPUT_SCHEMA
    schema_registry = SCHEMA_REGISTRY
    prompt_template = "acord-aligner"
    tools: list[str] = ["acord.lookup", "substrate.query", "artefact.write"]
    model_tier = "high"
    guardrails = [
        Guardrail(id="G2", description="verdict=partial requires a non-null deviation", check=_guardrail_g2_partial_requires_deviation),
        Guardrail(id="G3", description="a partial whose deviation echoes misfit language should have been misfit", check=_guardrail_g3_no_forced_fit),
    ]

    def __init__(self) -> None:
        self._returned_acord_refs: frozenset[str] = frozenset()

    def assemble_context(self, item: WorkItem, api: SubstrateApi) -> dict[str, Any]:
        """Deterministic given its input. Calls SubstrateApi.acord_lookup
        directly (not through the tool gateway) - the same precedent
        Repository Scout/Semantic Resolver already set for reading via
        substrate rather than routing every read through a tool call.
        Records the returned acordRefs as per-invocation instance state
        for validate_semantics' own G1 check below."""
        cluster = item.payload["cluster"]
        run_id = str(item.payload["run_id"])
        query = str(cluster.get("proposedConcept", ""))
        concepts = api.acord_lookup(run_id, query) if query else []
        self._returned_acord_refs = frozenset(f"acord://{c.acord_ref}" for c in concepts)
        acord_results = [
            {"acordRef": f"acord://{c.acord_ref}", "entity": c.entity, "attribute": c.attribute, "definition": "", "score": 0.0}
            for c in concepts
        ]
        return {"cluster": cluster, "acord_results": acord_results}

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """G1: "verdict=fit REQUIRES an acordRef returned by acord.lookup
        in this invocation. A remembered or invented ref is a
        violation." - the anti-hallucination control that matters most
        for this agent (standards references are exactly the kind of
        plausible detail a model will invent)."""
        if output.get("verdict") != "fit":
            return []
        acord_ref = output.get("acordRef")
        if acord_ref not in self._returned_acord_refs:
            return [Violation(
                level="V2", code="G1-uncited-acord-reference",
                detail=f"verdict=fit cites acordRef {acord_ref!r}, not returned by acord.lookup in this invocation",
                record_id=str(acord_ref),
            )]
        return []


def degraded_alignment(cluster: C6Conceptcluster) -> dict[str, Any]:
    """Section 19.2's degraded mode, literally: "acord-aligner is
    disabled. S5 emits verdict: unassessed for every cluster." No model
    call, no tool call - purely mechanical."""
    return {
        "clusterId": str(unwrap_ref(cluster.clusterId)),
        "acordRef": None,
        "verdict": "unassessed",
        "deviation": None,
        "rationale": DEGRADED_MODE_RATIONALE,
        "evidenceRefs": [str(unwrap_ref(ref)) for ref in cluster.evidenceRefs],
    }


def _work_item_for(cluster: C6Conceptcluster, run_id: str) -> WorkItem:
    return WorkItem(
        item_id=f"align-{unwrap_ref(cluster.clusterId)}", stage="S5", kind="align-cluster",
        payload={"cluster": cluster.model_dump(mode="json"), "run_id": run_id},
    )


def align_or_degrade(
    clusters: Sequence[C6Conceptcluster],
    ctx: RunContext,
    *,
    licence_disposition: str,
    agent: AcordAlignerAgent | None = None,
) -> Iterator[C7Alignmentrecord]:
    """The top-level dispatcher enforcing G4. licence_disposition is an
    explicit, injected string (not read from a feature flag inside this
    function) - the caller is honest about the fact that no real ACORD
    licence exists to check in this repo, matching the DI convention
    gate/gate.py and substrate/ingest.py already use."""
    if licence_disposition != "permitted":
        for cluster in clusters:
            yield C7Alignmentrecord.model_validate(degraded_alignment(cluster))
        return

    aligner = agent or AcordAlignerAgent()
    for cluster in clusters:
        item = _work_item_for(cluster, str(ctx.run_id))
        result = aligner.invoke(item, ctx)
        yield C7Alignmentrecord.model_validate(result.output)
