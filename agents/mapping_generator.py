"""
Mapping Generator (Appendix B) - the twelfth and final agent, closing the
roster. One invocation covers one whole region contract: the prompt's own
[INPUT] block passes the complete, in-scope region attribute list ("a
complete list, in scope order"), and Rule 1 requires an entry for every
one of them, so a single output_schema document (the whole
contracts/C10/MappingSpec/1.0.json shape, not one entry) is produced per
call - a different invocation granularity than ACORD Aligner/Canonical
Synthesiser's own per-cluster calls.

That granularity is what makes G1 (Totality) a real, per-invocation
guardrail here, unlike the coverage-time Gate checks: everything G1 needs
(the full region attribute list) is already in hand for this one call.
`Guardrail.check`'s own `(output, ctx) -> list[Violation]` signature still
has no access to the agent instance, so G1 is implemented via
validate_semantics (which does, via self._region_records) - the same
constraint agents/acord_aligner.py's own G1 and
agents/canonical_synthesiser.py's own G3 already document. G2-G5 need no
per-invocation state and are real Guardrail objects.

G2 (closed transform vocabulary) and G4 (lossy transform requires a note)
both reuse mapping/parser.py and mapping/transforms.py directly rather
than re-deriving the vocabulary - the same "one source of truth" reasoning
mapping/compiler.py's own T2/T4 checks already follow; G3 here is
deliberately the same rule as compiler.py's T2, restated as an early,
per-invocation gate (the compiler is the eventual backstop over the whole
spec, this guardrail is what stops an obviously bad candidate from ever
reaching it).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from referencing import Registry, Resource

from generated.C10.MappingSpec._1_0 import C10Mappingspec

from mapping.parser import MappingParseError, parse_transform_expr
from mapping.transforms import TRANSFORMS

from agents.base import Agent, RunContext, WorkItem
from agents.validation import Guardrail, Violation

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTRACTS_DIR = _REPO_ROOT / "contracts"

_CRITICAL_WEIGHT = 5
_SILENT_FAILURES = {"skip", "default"}


def _load_schema_registry() -> Registry:
    files = sorted(_CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text(encoding="utf-8")) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


SCHEMA_REGISTRY = _load_schema_registry()
OUTPUT_SCHEMA: dict[str, Any] = json.loads(
    (_CONTRACTS_DIR / "C10" / "MappingSpec" / "1.0.json").read_text(encoding="utf-8")
)

TRANSFORM_SIGNATURES = {name: spec.signature for name, spec in TRANSFORMS.items()}


def _parsed_chain_or_none(transform: str | None) -> list[Any] | None:
    if not transform:
        return None
    try:
        return list(parse_transform_expr(transform))
    except MappingParseError:
        return None


def _guardrail_g2_closed_transform_vocabulary(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G2: "Transform names MUST come from the closed library (10.3). An
    unknown transform is a violation, not an extension.\""""
    violations: list[Violation] = []
    for entry in output.get("mappings", []):
        transform = entry.get("transform")
        if not transform:
            continue
        try:
            calls = parse_transform_expr(transform)
        except MappingParseError as err:
            violations.append(
                Violation(level="V4", code="G2-unparseable-transform", detail=str(err), record_id=entry.get("canonical"))
            )
            continue
        for call in calls:
            if call.name not in TRANSFORMS:
                violations.append(
                    Violation(
                        level="V4",
                        code="G2-unknown-transform",
                        detail=f"{call.name!r} is not in the closed transform library",
                        record_id=entry.get("canonical"),
                    )
                )
    return violations


def _guardrail_g3_weight_5_forbids_silent_failure(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G3: "weight >= 5 MUST NOT carry onFailure: skip or default.\""""
    violations: list[Violation] = []
    for entry in output.get("mappings", []):
        weight = entry.get("weight")
        on_failure = entry.get("onFailure")
        if weight is not None and weight >= _CRITICAL_WEIGHT and on_failure in _SILENT_FAILURES:
            violations.append(
                Violation(
                    level="V4",
                    code="G3-weight-5-silent-failure",
                    detail=f"weight>=5 requires reject or escalate, got onFailure={on_failure!r}",
                    record_id=entry.get("canonical"),
                )
            )
    return violations


def _guardrail_g4_lossy_transform_requires_note(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G4: "Any lossy transform MUST be declared as a loss with a note.\""""
    violations: list[Violation] = []
    for entry in output.get("mappings", []):
        calls = _parsed_chain_or_none(entry.get("transform"))
        if calls is None:
            continue
        if any(TRANSFORMS[c.name].lossy for c in calls if c.name in TRANSFORMS) and not entry.get("note"):
            violations.append(
                Violation(
                    level="V4",
                    code="G4-undeclared-lossy-transform",
                    detail=f"{entry.get('transform')!r} is lossy but carries no note",
                    record_id=entry.get("canonical"),
                )
            )
    return violations


def _guardrail_g5_evidence_cited(output: dict[str, Any], ctx: RunContext) -> list[Violation]:
    """G5: "Every entry MUST cite the evref supporting the region path."
    Schema-enforced already (evidence: minItems: 1); restated here
    defensively, the same posture ACORD Aligner's own G5-equivalent
    checks take on schema-backed rules."""
    violations: list[Violation] = []
    for entry in output.get("mappings", []):
        if not entry.get("evidence"):
            violations.append(
                Violation(level="V4", code="G5-missing-evidence", detail="entry cites no evidence", record_id=entry.get("canonical"))
            )
    return violations


class MappingGeneratorAgent(Agent):
    agent_id = "mapping-generator"
    family = "assurance"
    output_schema = OUTPUT_SCHEMA
    schema_registry = SCHEMA_REGISTRY
    prompt_template = "mapping-generator"
    tools: list[str] = ["substrate.query", "artefact.write"]
    model_tier = "high"
    guardrails = [
        Guardrail(id="G2", description="transform names come from the closed library", check=_guardrail_g2_closed_transform_vocabulary),
        Guardrail(id="G3", description="weight>=5 forbids onFailure skip/default", check=_guardrail_g3_weight_5_forbids_silent_failure),
        Guardrail(id="G4", description="a lossy transform is declared with a note", check=_guardrail_g4_lossy_transform_requires_note),
        Guardrail(id="G5", description="every entry cites evidence", check=_guardrail_g5_evidence_cited),
    ]

    def __init__(self) -> None:
        self._region_records: list[dict[str, Any]] = []

    def assemble_context(self, item: WorkItem, api: Any) -> dict[str, Any]:
        """Deterministic given its input. Records the region attribute
        list as per-invocation instance state - G1 (validate_semantics,
        below) needs it, and Agent's own validate_semantics(output, ctx)
        signature has no `item` parameter (the same constraint
        agents/acord_aligner.py and agents/canonical_synthesiser.py
        already work within)."""
        self._region_records = item.payload["region_records"]
        return {
            "region_records": item.payload["region_records"],
            "canonical_model": item.payload["canonical_model"],
            "transform_signatures": TRANSFORM_SIGNATURES,
            "cluster_map": item.payload["cluster_map"],
        }

    def validate_semantics(self, output: dict[str, Any], ctx: RunContext) -> list[Violation]:
        """G1: "Every region attribute in scope MUST appear, mapped or
        with an explicit disposition and reason" - restated for the
        model, the same way Rule 1 restates it for the prompt; the
        compiler's own T1 is the eventual backstop over the whole spec."""
        covered = {entry.get("region") for entry in output.get("mappings", []) if entry.get("region")}
        violations: list[Violation] = []
        for record in self._region_records:
            path = record.get("path")
            if path is not None and path not in covered:
                violations.append(
                    Violation(level="V2", code="G1-totality", detail=f"{path} has no mapping entry", record_id=path)
                )
        return violations


def _work_item_for(
    region_records: list[dict[str, Any]],
    canonical_model: dict[str, Any],
    cluster_map: dict[str, Any],
    mapping_spec_id: str,
) -> WorkItem:
    return WorkItem(
        item_id=f"generate-mapping-{mapping_spec_id}",
        stage="S8",
        kind="generate-mapping",
        payload={
            "region_records": region_records,
            "canonical_model": canonical_model,
            "cluster_map": cluster_map,
        },
    )


GenerateMappingFn = Callable[
    ["list[dict[str, Any]]", "dict[str, Any]", "dict[str, Any]", str], C10Mappingspec
]


def make_mapping_generator_factory(
    ctx: RunContext, *, agent: MappingGeneratorAgent | None = None,
) -> GenerateMappingFn:
    """A factory, the same shape as make_canonical_synthesiser_factory/
    make_repository_scout_classifier - the caller needs a RunContext
    threaded through. Unlike Canonical Synthesiser's own factory, there is
    no legitimate "no output" outcome here (Rule 1's totality means every
    invocation must produce a full spec, one way or another for every
    attribute) - WorkItemFailed propagates to the caller on a genuine
    failure rather than being caught and downgraded."""
    generator = agent or MappingGeneratorAgent()

    def _generate(
        region_records: list[dict[str, Any]],
        canonical_model: dict[str, Any],
        cluster_map: dict[str, Any],
        mapping_spec_id: str,
    ) -> C10Mappingspec:
        item = _work_item_for(region_records, canonical_model, cluster_map, mapping_spec_id)
        result = generator.invoke(item, ctx)
        return C10Mappingspec.model_validate(result.output)

    return _generate
