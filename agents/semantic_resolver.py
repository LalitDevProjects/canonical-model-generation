"""
Semantic Resolver (Section 7.5.1). Adjudicates only the REVIEW-BAND
material algorithms/clustering.py::run_clustering() sets aside (score in
[review_band_low, link_threshold)) - the deterministic pipeline decides
every confidently-linked pair on its own, with zero LLM dependency (this
increment's confirmed architecture). This mirrors exactly how Repository
Scout (Increment 6) adjudicates connectors/relevance.py's own
"uncertain" middle band for relevance filtering - see
make_semantic_resolver_adjudicator's own docstring below for the same
factory-for-signature-constraint shape make_repository_scout_classifier
already uses.

output_schema is the REAL, unmodified contracts/C6/ConceptCluster/1.0.json
(loaded from disk, not hand-copied) - a single source of truth. Because
that schema $refs into common/defs.json, this is also the first agent
whose output_schema needs Increment 7's new Agent.schema_registry /
validate_schema(..., registry=...) plumbing (agents/base.py,
agents/validation.py) to resolve at all.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from referencing import Registry, Resource

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster

from algorithms.clustering import ReviewPair
from algorithms.graph import connected_components
from algorithms.profiling import ProfiledAttribute
from contracts.validators import artefact_id_from_evref, unwrap_ref

from agents.base import Agent, RunContext, WorkItem
from agents.validation import Guardrail, Violation, validate_reference
from pipeline.run_store import RunStore, TriageEntry

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "contracts"


def _load_schema_registry() -> Registry:
    """Same pattern as tests/contracts/test_fixtures.py::_load_registry -
    every contracts/**/*.json resource registered by its own $id, so
    C6 ConceptCluster's $refs into common/defs.json resolve."""
    files = sorted(_CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text(encoding="utf-8")) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


SCHEMA_REGISTRY = _load_schema_registry()
OUTPUT_SCHEMA: dict[str, Any] = json.loads((_CONTRACTS_DIR / "C6" / "ConceptCluster" / "1.0.json").read_text(encoding="utf-8"))


def _known_artefact_ids(records: Sequence[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        for ref in record.get("evidenceRefs", []) or []:
            artefact_id = artefact_id_from_evref(str(ref))
            if artefact_id is not None:
                ids.add(artefact_id)
    return ids


def _guardrail_g1_evidence_per_member(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G1: "Every cluster MUST carry >= 1 resolvable evidenceRef per
    member." Checked by cross-referencing each member's own
    AttributeRecord (via substrate) against the cluster's own
    evidenceRefs list - a member whose real evidence doesn't overlap the
    cluster's cited evidence is unsupported."""
    violations: list[Violation] = []
    cluster_refs = {str(ref) for ref in output.get("evidenceRefs", []) or []}
    for member in output.get("members", []) or []:
        attribute_id = member.get("attributeId")
        try:
            record = ctx.substrate.get_attribute(str(ctx.run_id), str(attribute_id))
        except KeyError:
            violations.append(Violation(
                level="V4", code="G1-unresolvable-member",
                detail=f"member {attribute_id!r} has no corresponding AttributeRecord",
                record_id=attribute_id,
            ))
            continue
        member_refs = {str(unwrap_ref(ref)) for ref in record.evidenceRefs}
        if not (member_refs & cluster_refs):
            violations.append(Violation(
                level="V4", code="G1-no-evidence",
                detail=f"member {attribute_id!r} has no evidenceRef overlap with the cluster's own evidenceRefs",
                record_id=attribute_id,
            ))
    return violations


def _guardrail_g2_cross_region_needs_confidence(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G2: "A cluster with members from >1 region and conflictClass=none
    MUST have confidence >= 0.80, otherwise it MUST be reclassified or
    split.\""""
    members = output.get("members", []) or []
    regions = {m.get("region") for m in members}
    confidence = output.get("confidence", 0.0)
    if len(regions) > 1 and output.get("conflictClass") is None and confidence < 0.80:
        return [Violation(
            level="V4", code="G2-low-confidence-cross-region",
            detail=f"cross-region cluster with conflictClass=none needs confidence>=0.80, got {confidence}",
        )]
    return []


def _guardrail_g3_conflict_needs_alternative(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G3: "conflictClass != none MUST be accompanied by >= 1 alternative
    with a whyRejected explanation.\""""
    if output.get("conflictClass") is None:
        return []
    alternatives = output.get("alternatives") or []
    violations: list[Violation] = []
    if not alternatives:
        violations.append(Violation(level="V4", code="G3-missing-alternative", detail="conflictClass is set but no alternatives were given"))
    for alt in alternatives:
        if not str(alt.get("whyRejected", "")).strip():
            violations.append(Violation(level="V4", code="G3-empty-why-rejected", detail="an alternative's whyRejected is empty"))
    return violations


def _guardrail_g4_obligation_not_resolved_here(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G4: "Obligation conflicts MUST NOT be resolved here; classify and
    escalate." Operationalised as: a claimed conflictClass=obligation
    must correspond to a genuine obligation-level divergence among the
    real member records - the agent can't invent one to dodge a merge
    decision."""
    if output.get("conflictClass") != "obligation":
        return []
    levels = set()
    for member in output.get("members", []) or []:
        try:
            record = ctx.substrate.get_attribute(str(ctx.run_id), str(member.get("attributeId")))
        except KeyError:
            continue
        levels.add(record.obligation.level)
    if len(levels) <= 1:
        return [Violation(
            level="V4", code="G4-false-obligation-conflict",
            detail="conflictClass=obligation claimed but member obligation levels do not actually differ",
        )]
    return []


def _guardrail_g5_low_confidence_needs_dissent(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G5: "confidence < 0.80 MUST populate dissent.\""""
    confidence = output.get("confidence", 1.0)
    dissent = output.get("dissent")
    if confidence < 0.80 and not (dissent and str(dissent).strip()):
        return [Violation(level="V4", code="G5-missing-dissent", detail=f"confidence {confidence} < 0.80 but dissent is empty")]
    return []


class SemanticResolverAgent(Agent):
    agent_id = "semantic-resolver"
    family = "comprehension"
    output_schema = OUTPUT_SCHEMA
    schema_registry = SCHEMA_REGISTRY
    prompt_template = "semantic-resolver"
    tools: list[str] = ["substrate.query", "substrate.neighbours", "artefact.write"]
    model_tier = "high"
    guardrails = [
        Guardrail(id="G1", description="every cluster carries >=1 resolvable evidenceRef per member", check=_guardrail_g1_evidence_per_member),
        Guardrail(id="G2", description="cross-region conflictClass=none clusters need confidence>=0.80", check=_guardrail_g2_cross_region_needs_confidence),
        Guardrail(id="G3", description="conflictClass!=none needs >=1 alternative with whyRejected", check=_guardrail_g3_conflict_needs_alternative),
        Guardrail(id="G4", description="conflictClass=obligation must reflect a real obligation divergence", check=_guardrail_g4_obligation_not_resolved_here),
        Guardrail(id="G5", description="confidence<0.80 must populate dissent", check=_guardrail_g5_low_confidence_needs_dissent),
    ]

    def __init__(self) -> None:
        self._expected_attribute_ids: frozenset[str] = frozenset()
        self._known_artefact_ids: set[str] = set()

    def assemble_context(self, item: WorkItem, api: Any) -> dict[str, Any]:
        """Deterministic given its input. anchor/candidate_records are
        pre-serialised C5Attributerecord dicts (built by the work-item
        builder below) rather than re-derived here. Also records the
        input's own attributeId set and known artefact ids as
        per-invocation instance state, read back by validate_semantics()
        - the same "assemble_context/validate_semantics share self
        within one invoke()" idiom Repository Scout already uses, since
        Agent.validate_semantics(output, ctx) has no `item` parameter."""
        anchor = item.payload["anchor"]
        candidates = item.payload["candidates"]
        all_records = [anchor, *candidates]
        self._expected_attribute_ids = frozenset(str(r["attributeId"]) for r in all_records)
        self._known_artefact_ids = _known_artefact_ids(all_records)

        run_id = str(item.payload["run_id"])
        description = (anchor.get("semantics") or {}).get("description") or ""
        query = f"{anchor['localName']} {description}".strip()
        doc_chunks: list[dict[str, str]] = []
        if query:
            for chunk in api.search(run_id, query):
                doc_chunks.append({"evref": chunk.evref, "text": chunk.text})

        return {"anchor_record": anchor, "candidate_records": candidates, "doc_chunks": doc_chunks}

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """V2: (a) no invented members - every returned member's
        attributeId must be one of the anchor/candidates actually
        supplied (the agent may OMIT low-confidence members per its own
        [UNCERTAINTY] block, but may not invent new ones); (b) every
        evidenceRefs entry resolves against the input records' own
        already-I1-validated evidence (the self-referential known-set
        trick Schema Interpreter already uses - no CorpusManifest access
        needed)."""
        violations: list[Violation] = []
        member_ids = {str(m.get("attributeId")) for m in output.get("members", []) or []}
        for invented_id in sorted(member_ids - self._expected_attribute_ids):
            violations.append(Violation(
                level="V2", code="invented-member",
                detail=f"member {invented_id!r} was not among the supplied anchor/candidates",
                record_id=invented_id,
            ))
        refs = [str(r) for r in output.get("evidenceRefs", []) or []]
        violations.extend(validate_reference(refs, self._known_artefact_ids))
        return violations


def resolve_escalation(output: dict[str, Any]) -> tuple[bool, str]:
    """Section 7.5.1's escalation table - the two rules actionable
    without a real orchestrator. "members span > 3 source contracts ->
    adversarial-critic before S5" names an agent that doesn't exist until
    Increment 8/9 - documented as deferred, not acted on, the same
    honesty standard as algorithms/conflict.py::contradiction_detected."""
    if output.get("conflictClass") == "homonym":
        return True, "conflictClass=homonym"
    confidence = output.get("confidence", 1.0)
    if confidence < 0.60:
        return True, f"confidence {confidence} < 0.60"
    return False, ""


def _work_item_for(run_id: str, anchor: ProfiledAttribute, candidates: Sequence[ProfiledAttribute]) -> WorkItem:
    all_ids = sorted([anchor.record.attributeId, *(c.record.attributeId for c in candidates)])
    item_id = "resolve-" + "-".join(all_ids)[:120]
    return WorkItem(
        item_id=item_id, stage="S4", kind="review-group",
        payload={
            "run_id": run_id,
            "anchor": anchor.record.model_dump(mode="json"),
            "candidates": [c.record.model_dump(mode="json") for c in candidates],
        },
    )


def make_semantic_resolver_adjudicator(
    ctx: RunContext, *, agent: SemanticResolverAgent | None = None, run_store: RunStore | None = None,
) -> Callable[[Sequence[ReviewPair]], Iterator[C6Conceptcluster]]:
    """The real semantic-resolver adjudicator over review-band material -
    a factory, the same shape as
    agents.repository_scout.make_repository_scout_classifier, because the
    caller (whatever assembles review_pairs from
    algorithms.clustering.run_clustering) needs a RunContext threaded
    through, which a bare function over ReviewPairs alone has no room
    for. Groups review pairs into connected components (their own
    mini-graph, independent of the main clustering graph, since these
    are exactly the pairs that DIDN'T make it into that graph), builds
    one WorkItem per component (anchor = lexicographically-lowest
    attributeId), invokes the agent, and persists any AWAIT_TRIAGE
    escalation via the same triage-export sink
    algorithms.clustering.write_triage_export uses."""
    resolver = agent or SemanticResolverAgent()
    store = run_store or RunStore()

    def _adjudicate(review_pairs: Sequence[ReviewPair]) -> Iterator[C6Conceptcluster]:
        if not review_pairs:
            return

        by_id: dict[str, ProfiledAttribute] = {}
        edges: dict[frozenset[str], float] = {}
        for pair in review_pairs:
            by_id[pair.a.record.attributeId] = pair.a
            by_id[pair.b.record.attributeId] = pair.b
            edges[frozenset({pair.a.record.attributeId, pair.b.record.attributeId})] = pair.score

        for component_ids in connected_components(sorted(by_id), edges):
            members = [by_id[i] for i in component_ids]
            anchor = min(members, key=lambda m: m.record.attributeId)
            candidates = [m for m in members if m is not anchor]

            item = _work_item_for(str(ctx.run_id), anchor, candidates)
            result = resolver.invoke(item, ctx)
            cluster = C6Conceptcluster.model_validate(result.output)

            escalate, reason = resolve_escalation(result.output)
            if escalate:
                store.append_triage_entry(ctx.run_id, TriageEntry(
                    kind="agent-escalation",
                    reason=reason,
                    member_attribute_ids=tuple(str(m.attributeId) for m in cluster.members),
                    cluster_payload=result.output,
                ))
            yield cluster

    return _adjudicate
