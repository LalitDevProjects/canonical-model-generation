"""
Cross-artefact invariant checks (I1-I6, Section 3.2) that JSON Schema alone
cannot express, because each one requires context spanning more than one
document (e.g. "does this evidenceRef resolve against the run's actual
CorpusManifest" needs both records in hand at once; a single-document schema
cannot see the other document).

Important: this module is a companion to, not a replacement for, JSON Schema
validation. Some of the contracts (notably C7 AlignmentRecord's fit/partial/
misfit guardrails and C10 MappingSpec's transform-xor-disposition rule) use
if/then and oneOf conditionals that jsonschema.Draft202012Validator enforces
but the generated Pydantic models do NOT enforce on their own - constructing
a generated model successfully is not proof a document satisfies its schema.
Any code path that writes or accepts C1-C11 documents MUST run both
Draft202012Validator(schema).validate(instance) and the relevant checks in
this module, not either alone.

Every check_* function returns a list of violations rather than raising, so
callers can choose to aggregate-and-report (e.g. a fixture test wanting the
full list) or fail-fast (e.g. an egress path that should halt on the first
hit) at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C10.MappingSpec._1_0 import C10Mappingspec


@dataclass(frozen=True)
class InvariantViolation:
    """One failure of one invariant, attributable to one record."""

    invariant: str
    record_id: str
    detail: str


def _unwrap(value: object) -> object:
    """datamodel-code-generator does not consistently collapse RootModel
    wrapper classes for $ref-typed scalar fields: a bare single '$ref'
    property collapses to a plain constrained str, but the same $def used
    inside a list ('evidenceRefs: list[EvidenceRef]') or inside an anyOf
    (a nullable field) stays as a RootModel[str] instance whose str() is
    "root='...'", not the underlying value. Unwrap defensively via '.root'
    so comparisons/parsing below are correct regardless of which form a
    given field took, and remain correct if a future regeneration changes
    which fields get collapsed.
    """
    root = getattr(value, "root", None)
    return root if root is not None else value


def _artefact_id_from_evref(ref: str) -> str | None:
    """Extract the artefactId segment from an evref://{region}/{system}/{artefactId}@{hash}#{locator} URI."""
    prefix = "evref://"
    if not ref.startswith(prefix):
        return None
    rest = ref[len(prefix):]
    parts = rest.split("/", 2)
    if len(parts) != 3:
        return None
    tail = parts[2]
    artefact_id = tail.split("@", 1)[0]
    return artefact_id or None


def check_i1_evidence_resolvable(
    attributes: Sequence[C5Attributerecord],
    manifest: C4Corpusmanifest,
) -> list[InvariantViolation]:
    """I1: every AttributeRecord.evidenceRefs entry MUST resolve to an artefact
    listed in the run's CorpusManifest."""
    known_artefact_ids = {str(_unwrap(a.artefactId)) for a in manifest.artefacts}
    violations: list[InvariantViolation] = []
    for attr in attributes:
        for ref in attr.evidenceRefs:
            ref_value = str(_unwrap(ref))
            artefact_id = _artefact_id_from_evref(ref_value)
            if artefact_id is None or artefact_id not in known_artefact_ids:
                violations.append(InvariantViolation(
                    invariant="I1",
                    record_id=str(_unwrap(attr.attributeId)),
                    detail=f"evidenceRef {ref_value!r} does not resolve to any artefact in the CorpusManifest",
                ))
    return violations


def check_i2_cluster_members_same_run(
    clusters: Sequence[C6Conceptcluster],
    attributes: Sequence[C5Attributerecord],
    run_id: str,
) -> list[InvariantViolation]:
    """I2: every ConceptCluster member MUST reference an AttributeRecord
    produced within the same run."""
    attrs_by_id = {str(_unwrap(a.attributeId)): a for a in attributes}
    violations: list[InvariantViolation] = []
    for cluster in clusters:
        cluster_id = str(_unwrap(cluster.clusterId))
        for member in cluster.members:
            member_attr_id = str(_unwrap(member.attributeId))
            attr = attrs_by_id.get(member_attr_id)
            if attr is None:
                violations.append(InvariantViolation(
                    invariant="I2",
                    record_id=cluster_id,
                    detail=f"member attributeId {member_attr_id!r} has no corresponding AttributeRecord",
                ))
            elif str(attr.runId) != str(run_id):
                violations.append(InvariantViolation(
                    invariant="I2",
                    record_id=cluster_id,
                    detail=f"member attributeId {member_attr_id!r} belongs to run {attr.runId}, not {run_id}",
                ))
    return violations


def check_i3_candidate_traces_to_attribute(
    candidates: Sequence[C8Canonicalcandidate],
    clusters: Sequence[C6Conceptcluster],
    attributes: Sequence[C5Attributerecord],
) -> list[InvariantViolation]:
    """I3: every CanonicalCandidate MUST trace to at least one ConceptCluster,
    and transitively to at least one AttributeRecord."""
    clusters_by_id = {str(_unwrap(c.clusterId)): c for c in clusters}
    attr_ids = {str(_unwrap(a.attributeId)) for a in attributes}
    violations: list[InvariantViolation] = []
    for cand in candidates:
        candidate_id = str(_unwrap(cand.candidateId))
        if not cand.clusterRefs:
            violations.append(InvariantViolation(
                invariant="I3",
                record_id=candidate_id,
                detail="no clusterRefs present",
            ))
            continue
        for cluster_ref in cand.clusterRefs:
            cluster_ref_value = str(_unwrap(cluster_ref))
            cluster = clusters_by_id.get(cluster_ref_value)
            if cluster is None:
                violations.append(InvariantViolation(
                    invariant="I3",
                    record_id=candidate_id,
                    detail=f"clusterRef {cluster_ref_value!r} does not resolve to a known ConceptCluster",
                ))
                continue
            if not any(str(_unwrap(m.attributeId)) in attr_ids for m in cluster.members):
                violations.append(InvariantViolation(
                    invariant="I3",
                    record_id=candidate_id,
                    detail=f"cluster {cluster_ref_value!r} has no member tracing to a known AttributeRecord",
                ))
    return violations


def check_i4_coverage_scored_attributes_evidenced(
    report: C9Coveragereport,
    scored_attributes: Sequence[dict[str, object]],
) -> list[InvariantViolation]:
    """I4: every scored attribute contributing to a CoverageReport MUST have
    both an evidence reference and a named ratifying SME before it can
    contribute a non-zero score.

    CoverageReport itself (as designed at Increment 1) is an aggregate and
    carries no per-attribute detail, so this check operates on the raw
    pre-aggregation universe the coverage algorithm (Increment 8) will
    consume, not on the report alone: {"conceptId": str, "evidenceRefs":
    list[str], "ratifyingSme": str | None}.
    """
    violations: list[InvariantViolation] = []
    for entry in scored_attributes:
        concept_id = str(entry.get("conceptId", "<unknown>"))
        evidence_refs = entry.get("evidenceRefs") or []
        sme = entry.get("ratifyingSme")
        if not evidence_refs or not sme:
            violations.append(InvariantViolation(
                invariant="I4",
                record_id=f"{report.domain}:{concept_id}",
                detail="scored attribute contributes to CoverageReport without both an evidence reference and a named ratifying SME",
            ))
    return violations


def check_i5_mapping_entries_have_disposition(
    spec: C10Mappingspec,
) -> list[InvariantViolation]:
    """I5: every MappingSpec entry MUST carry a disposition - mapped
    (transform present), unmapped with a reason, or escalated with a reason.
    Omission, or carrying both, is a validation error.

    The C10 schema's mappings[].oneOf(transform, disposition) already
    enforces this at the jsonschema level; this is a belt-and-braces re-check
    that also runs against Pydantic-only-validated documents, where the
    oneOf's mutual exclusivity is NOT enforced (see module docstring).
    """
    violations: list[InvariantViolation] = []
    spec_id = spec.header.mappingSpecId
    for index, entry in enumerate(spec.mappings):
        transform = getattr(entry, "transform", None)
        disposition = getattr(entry, "disposition", None)
        record_id = f"{spec_id}[{index}]"
        if transform is not None and disposition is not None:
            violations.append(InvariantViolation(
                invariant="I5",
                record_id=record_id,
                detail="entry carries both transform and disposition; exactly one is required",
            ))
        elif transform is None and disposition is None:
            violations.append(InvariantViolation(
                invariant="I5",
                record_id=record_id,
                detail="entry carries neither transform nor disposition",
            ))
        elif disposition is not None and not disposition.reason:
            violations.append(InvariantViolation(
                invariant="I5",
                record_id=record_id,
                detail="disposition present without a reason",
            ))
    return violations


def check_i6_ledger_chain_unbroken(
    entries: Sequence[C3Egressledgerentry],
) -> list[InvariantViolation]:
    """I6: EgressLedgerEntry.prevHash MUST form an unbroken chain per region.
    A break invalidates the run and requires manual investigation.

    entries MUST be for a single region, in append order. The first entry in
    a region's chain (the genesis entry) is expected to carry prevHash=null;
    every subsequent entry's prevHash MUST equal the previous entry's hash.
    """
    violations: list[InvariantViolation] = []
    if entries:
        regions = {str(_unwrap(e.region)) for e in entries}
        if len(regions) > 1:
            violations.append(InvariantViolation(
                invariant="I6",
                record_id="<multiple>",
                detail=f"entries span multiple regions ({sorted(regions)}); chain check requires a single region's entries in append order",
            ))
            return violations

    previous_hash: str | None = None
    for index, entry in enumerate(entries):
        prev_hash = _unwrap(entry.prevHash)
        if index == 0:
            if prev_hash is not None:
                violations.append(InvariantViolation(
                    invariant="I6",
                    record_id=entry.entryId,
                    detail="genesis entry (first in region chain) must have prevHash=null",
                ))
        elif str(prev_hash) != str(previous_hash):
            violations.append(InvariantViolation(
                invariant="I6",
                record_id=entry.entryId,
                detail=f"prevHash {prev_hash!r} does not match previous entry's hash {previous_hash!r}; chain broken",
            ))
        previous_hash = str(_unwrap(entry.hash))
    return violations
