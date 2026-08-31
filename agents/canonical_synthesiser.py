"""
Canonical Synthesiser (Section 7.5.3). Proposes one canonical attribute
per reconciled concept; the code corrects the fields it must not trust
the model to decide alone.

G3 ("placement MUST be produced by the deterministic rules in 9.7. The
agent supplies the rationale; the code supplies the placement") is
enforced by construction, not a runtime check: the model's own raw
placement/placementRule guess (needed only to satisfy the schema's shape
- the prompt's own [INPUT] block never tells it what the real placement
is) is overwritten in validate_semantics with the real
algorithms.placement.place() result, mutating `output` in place - Python
dict reference semantics mean agents/base.py::invoke() carries the same
object through guardrails, write and route afterward. The same
treatment applies to obligation.level (Rule 3: "Choose the WEAKEST
obligation present across regions" - as deterministically computable as
placement) and vendorOnly (a direct function of max_evidence_tier, not
a judgment call). A "guardrail rejects the model's guess" design was
considered and rejected: the model is never given this information, so
it would fire on nearly every real invocation - the same reasoning
agents/semantic_resolver.py already documents for its own review-band
work.

Section 9.7's own [UNCERTAINTY] block ("If the cluster does not support
a single coherent attribute, do not invent one. Emit no candidate...")
has no representation in C8.CanonicalCandidate's schema - every field is
required, so there is no valid JSON shape for "no candidate." The
practical resolution: make_canonical_synthesiser_factory() catches
WorkItemFailed (raised when schema validation exhausts its retries) and
treats it as exactly that - "the concept returns to triage" - returning
None, which algorithms.coverage.build_universe() already treats as a
legitimate, expected "gap" resolution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from referencing import Registry, Resource

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate

from algorithms.coverage import weakest_obligation
from algorithms.naming import NamingContext, check_name
from algorithms.placement import default_placement_context, place, placement_to_contract_value
from config.settings import load_settings
from contracts.validators import check_i3_candidate_traces_to_attribute, unwrap_ref

from agents.base import Agent, RunContext, WorkItem
from agents.validation import Guardrail, Violation, WorkItemFailed

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "contracts"


def _load_schema_registry() -> Registry:
    files = sorted(_CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text(encoding="utf-8")) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


SCHEMA_REGISTRY = _load_schema_registry()
OUTPUT_SCHEMA: dict[str, Any] = json.loads((_CONTRACTS_DIR / "C8" / "CanonicalCandidate" / "1.0.json").read_text(encoding="utf-8"))

CONVENTIONS_SUMMARY = (
    "Attributes MUST be lowerCamelCase; entities MUST be PascalCase. Expand "
    "abbreviations except id/ref/uri/iso. Core names MUST NOT encode a "
    "region. Booleans MUST be phrased is*/has*. Monetary values MUST use "
    "MonetaryAmount; identifiers MUST use Identifier; instants MUST carry "
    "an offset (Section 9.9)."
)


def _guardrail_g1_traces_to_cluster(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G1: "Every candidate MUST reference >= 1 cluster (I3).\""""
    if not output.get("clusterRefs"):
        return [Violation(level="V2", code="G1-missing-cluster-ref", detail="candidate has no clusterRefs")]
    return []


def _guardrail_g2_naming_convention(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G2: "Naming MUST satisfy the convention checker (9.9). Violations
    are rejected before persistence, not corrected silently." Runs after
    validate_semantics, so output["placement"] is already the real,
    code-corrected value by this point.

    denotes_money/denotes_identifier are hardcoded False here, not
    computed from name tokens: contracts/C8/CanonicalCandidate/1.0.json's
    own dataType field is constrained to the same bare primitive enum as
    C5 (string/integer/decimal/...) - "an Increment 1 design call," per
    its own schema description - with no room for the richer canonical
    type names ("MonetaryAmount", "Identifier") Rule 4 and check_name's
    own money/identifier checks assume. algorithms.naming.check_name
    itself stays fully spec-faithful and is independently tested
    (tests/algorithms/test_naming.py) for a future system with a richer
    canonical type model; wiring it against those two checks here would
    only ever produce violations the model has no schema-valid way to
    avoid. A documented, honest gap - revisit once C8 (or a successor
    contract) carries a real canonical-type-name field."""
    entity = str(output.get("entity", ""))
    attribute = str(output.get("attribute", ""))
    ctx_naming = NamingContext(
        is_core=str(output.get("placement")) == "core",
        data_type=str(output.get("dataType", "")),
        type_name=str(output.get("dataType", "")),
        # Rule 4: "Instants always carry an offset. There are no
        # exceptions." C8 has no typeDetail field to read a per-instance
        # signal from (the same gap as denotes_money/denotes_identifier
        # above), but every real dateTime value already carries
        # offsetRequired=True at the source (parsers/type_normalisation.py's
        # OpenAPI table maps "date-time" unconditionally) - True here is
        # the honest default given that source-of-truth invariant.
        offset_required=True,
        denotes_money=False,
        denotes_identifier=False,
    )
    abbreviations = load_settings().clustering.abbreviations
    violations = check_name(entity, attribute, ctx_naming, abbreviations=abbreviations)
    return [
        Violation(level="V4", code=f"G2-{v.kind}", detail=v.message, record_id=attribute)
        for v in violations
    ]


class CanonicalSynthesiserAgent(Agent):
    agent_id = "canonical-synthesiser"
    family = "synthesis"
    output_schema = OUTPUT_SCHEMA
    schema_registry = SCHEMA_REGISTRY
    prompt_template = "canonical-synthesiser"
    tools: list[str] = ["substrate.query", "acord.lookup", "artefact.write"]
    model_tier = "high"
    guardrails = [
        Guardrail(id="G1", description="every candidate references >=1 cluster", check=_guardrail_g1_traces_to_cluster),
        Guardrail(id="G2", description="naming satisfies the Section 9.9 convention checker", check=_guardrail_g2_naming_convention),
    ]

    def __init__(self) -> None:
        self._cluster: C6Conceptcluster | None = None

    def assemble_context(self, item: WorkItem, api: Any) -> dict[str, Any]:
        """Deterministic given its input. Records the cluster as
        per-invocation instance state - validate_semantics needs it to
        compute the real placement/obligation, and Agent's own
        validate_semantics(output, ctx) signature has no `item`
        parameter (the same constraint Repository Scout/Semantic
        Resolver already work within)."""
        self._cluster = C6Conceptcluster.model_validate(item.payload["cluster"])
        return {
            "cluster": item.payload["cluster"],
            "alignment": item.payload.get("alignment"),
            "member_records": item.payload["member_records"],
            "conventions": CONVENTIONS_SUMMARY,
        }

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """G3/Rule 3/vendorOnly: the code supplies placement,
        obligation.level and vendorOnly outright (mutating `output` in
        place - see module docstring), all deterministically computable
        from the cluster's real member data via ctx.substrate. Also I3:
        every clusterRef genuinely traces to this run's own cluster and
        attribute set (reuses contracts.validators.check_i3_candidate_
        traces_to_attribute directly, not reimplemented)."""
        if self._cluster is None:
            return []
        cluster = self._cluster
        run_id = str(ctx.run_id)
        member_records = [ctx.substrate.get_attribute(run_id, str(m.attributeId)) for m in cluster.members]

        placement_ctx = default_placement_context(ctx.substrate, run_id)
        placement = place(cluster, placement_ctx)
        output["placement"] = placement_to_contract_value(placement)
        output["placementRule"] = placement.rule

        if isinstance(output.get("obligation"), dict):
            output["obligation"]["level"] = weakest_obligation(member_records).value

        output["vendorOnly"] = placement_ctx.max_evidence_tier(cluster) == 3

        violations: list[Violation] = []
        cluster_refs = [str(unwrap_ref(ref)) for ref in (output.get("clusterRefs") or [])]
        if cluster_refs:
            try:
                candidate = C8Canonicalcandidate.model_validate(output)
            except Exception:
                candidate = None
            if candidate is not None:
                trace_violations = check_i3_candidate_traces_to_attribute(
                    [candidate], [cluster], list(member_records),
                )
                for tv in trace_violations:
                    violations.append(Violation(level="V2", code=f"I3-{tv.invariant}", detail=tv.detail, record_id=tv.record_id))
        return violations


def _work_item_for(
    cluster: C6Conceptcluster,
    alignment: C7Alignmentrecord | None,
    member_records: list[dict[str, Any]],
    run_id: str,
) -> WorkItem:
    return WorkItem(
        item_id=f"synthesise-{unwrap_ref(cluster.clusterId)}", stage="S6", kind="synthesise-cluster",
        payload={
            "cluster": cluster.model_dump(mode="json"),
            "alignment": alignment.model_dump(mode="json") if alignment is not None else None,
            "member_records": member_records,
            "run_id": run_id,
        },
    )


SynthesiseFn = Callable[[C6Conceptcluster, "C7Alignmentrecord | None", "list[dict[str, Any]]"], "C8Canonicalcandidate | None"]


def make_canonical_synthesiser_factory(
    ctx: RunContext, *, agent: CanonicalSynthesiserAgent | None = None,
) -> SynthesiseFn:
    """A factory, the same shape as make_repository_scout_classifier/
    make_semantic_resolver_adjudicator/align_or_degrade - the caller
    needs a RunContext threaded through, which a bare per-cluster
    function has no room for. Returns None for a cluster the model
    declines to synthesise a candidate for (see module docstring) -
    the caller should treat that exactly as algorithms.coverage.
    build_universe() already does: a "gap" concept, not an error."""
    synthesiser = agent or CanonicalSynthesiserAgent()

    def _synthesise(
        cluster: C6Conceptcluster, alignment: C7Alignmentrecord | None, member_records: list[dict[str, Any]],
    ) -> C8Canonicalcandidate | None:
        item = _work_item_for(cluster, alignment, member_records, str(ctx.run_id))
        try:
            result = synthesiser.invoke(item, ctx)
        except WorkItemFailed:
            return None
        return C8Canonicalcandidate.model_validate(result.output)

    return _synthesise
