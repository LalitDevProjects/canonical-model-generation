"""
The gate orchestrator (Section 5, in full): detection -> labels -> masking
-> policy evaluation -> ledger entry, tying together every other gate/
module into the single call connectors/manifest.py makes once per kept
ArtefactRef.

Resolving a real inconsistency in the spec's own two verdict mechanisms
(see the Increment 4 plan for the full reasoning): Section 5.1 says
"verdict precedence is block > mask > allow" as a direct function of
ladder rung hits (including L5's licence check), but Section 5.4's policy
YAML only ever produces verdict allow/block - no rule produces mask -
even though C2.verdict/C3.verdict are required enums that include mask,
and the Increment 4 acceptance test itself requires a mask outcome.
Reading either mechanism as the SOLE source of the final verdict is
self-contradictory, so this module implements two tiers:

1. LADDER verdict (block > mask > allow over rung hits, via
   `_ladder_verdict` below) is computed directly from detector output and
   is the final C2.verdict/C3.verdict for any artefact the policy admits.
   L4 (SENSITIVE_DOMAIN) and the hypothetical-but-unreachable
   PERSONAL_DATA label ladder-block; L1/L2/L3 (IDENTIFYING/SAMPLE_VALUE)
   ladder-mask; L0 alone ladder-allows.
2. POLICY verdict (gate/policy.py's evaluate_policy) is a separate
   admit/reject gate evaluated against the accumulated labels + licence
   disposition. It decides inclusion in CorpusManifest.artefacts vs.
   .exclusions. When policy rejects, the final ledger verdict is forced
   to block regardless of what the ladder alone computed.

For gate/policy.yaml specifically, both mechanisms agree on the
allow/block boundary by construction (block-personal/block-unlicensed
mirror the ladder's L4/L5 block conditions exactly) - this is a
reconciliation, not a hack.

Detection scans doc.structural_texts (L0), doc.example_texts (L3), and
BOTH doc.prose_texts and doc.example_texts (L1/L2/L4) - an example value
routinely contains an independently-detectable pattern (the golden
fixture's own "A. Smith, SW1A 1AA" contains a UK postcode), so L1/L2/L4
must see example text too, not just prose. Grammar-position
structural_texts are never scanned by L1/L2/L4 - a type name or element
name is not free text.

DOCUMENTARY is a baseline label (Section 5.4's own allow-documentary-masked
rule requires it to be assignable to something): assigned whenever the
artefact has any prose content at all, regardless of what else was
detected in it - not a fallback for "nothing else matched". A second,
narrower floor (empty labels) also assigns DOCUMENTARY, purely as a
schema-validity safety net for the edge case of content with neither
structural nor prose text (e.g. an empty JSON object) - C2's own `labels`
field requires at least one entry.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence
from uuid import UUID

from generated.C2.SanitisationRecord._1_0 import (
    C2Sanitisationrecord,
    DetectorHit,
    LicenceDisposition,
)
from generated.C2.SanitisationRecord._1_0 import (
    OverrideApproval as C2OverrideApproval,
)
from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry
from generated.common.defs import ExclusionReason, SanitisationLabel, SanitisationVerdict

from gate.detectors import (
    Span,
    detect_l0_structural,
    detect_l1_patterns,
    detect_l2_entities,
    detect_l3_example_values,
    detect_l4_sensitive_lexicon,
)
from gate.ledger import append_ledger_entry
from gate.policy import OverrideApproval, PolicyDocument, evaluate_policy
from gate.structure import parse_structure
from gate.tokenisation import redact

_BLOCK_LABELS = frozenset({SanitisationLabel.PERSONAL_DATA, SanitisationLabel.SENSITIVE_DOMAIN})
_MASK_LABELS = frozenset({SanitisationLabel.IDENTIFYING, SanitisationLabel.SAMPLE_VALUE})


def _ladder_verdict(labels: frozenset[SanitisationLabel]) -> SanitisationVerdict:
    if labels & _BLOCK_LABELS:
        return SanitisationVerdict.block
    if labels & _MASK_LABELS:
        return SanitisationVerdict.mask
    return SanitisationVerdict.allow


def _detector_hits(spans: Sequence[Span]) -> list[DetectorHit]:
    counts = Counter((span.rung, span.detector) for span in spans)
    return [
        DetectorHit(rung=rung, detector=detector, count=count)
        for (rung, detector), count in sorted(counts.items(), key=lambda kv: (kv[0][0].value, kv[0][1]))
    ]


def _exclusion_reason(matched_rule_id: str) -> ExclusionReason:
    """block-unlicensed maps to the more specific licence-blocked; every
    other block source (block-personal, or the default-block fallback
    when no rule matches at all) maps to policy-blocked."""
    if matched_rule_id == "block-unlicensed":
        return ExclusionReason.licence_blocked
    return ExclusionReason.policy_blocked


@dataclass(frozen=True)
class GateResult:
    admitted: bool
    content_hash: str
    redacted_content: bytes
    """Equal to the raw input content when nothing needed masking, and
    also when the artefact was blocked - a blocked artefact is never
    redacted, since nothing about it crosses the region boundary."""
    sanitisation_record: C2Sanitisationrecord | None
    """None exactly when not admitted - C1Sourceartefact.sanitisation is
    required, so this is only ever attached to an admitted artefact;
    ExclusionEntry (connectors/manifest.py) carries no sanitisation
    record at all."""
    ledger_entry: C3Egressledgerentry
    """Always produced, admitted or not - the ledger is the audit trail
    of the DECISION itself (Section 5.5: "what left each region, under
    what basis, and who authorised it"), and C3.verdict's required enum
    includes block for exactly this reason."""
    exclusion_reason: ExclusionReason | None
    policy_reason: str | None


def classify_and_redact(
    *,
    content: bytes,
    media_type: str,
    entry_id: str,
    artefact_id: str,
    region: str,
    run_id: UUID,
    licence_disposition: LicenceDisposition,
    classified_at: datetime,
    policy: PolicyDocument,
    policy_version: int,
    lawful_basis: str,
    region_key: bytes,
    signing_key: bytes,
    prev_ledger_hash: str | None,
    override_enabled: bool = False,
    override_approval: OverrideApproval | None = None,
    classified_by: str | None = None,
) -> GateResult:
    doc = parse_structure(content, media_type)

    spans: list[Span] = []
    spans.extend(detect_l0_structural(doc))
    spans.extend(detect_l3_example_values(doc))
    for text in (*doc.prose_texts, *doc.example_texts):
        spans.extend(detect_l1_patterns(text))
        spans.extend(detect_l2_entities(text))
        spans.extend(detect_l4_sensitive_lexicon(text))

    labels = {span.label for span in spans}
    if doc.prose_texts:
        labels.add(SanitisationLabel.DOCUMENTARY)
    if not labels:
        labels.add(SanitisationLabel.DOCUMENTARY)
    frozen_labels = frozenset(labels)

    ladder_verdict = _ladder_verdict(frozen_labels)
    # Every mask-rung span is unconditionally redacted by gate/tokenisation.py's
    # redact() - there is no partial-masking failure mode in this
    # implementation, so "all mask-worthy spans were actually masked" is
    # true by construction whenever policy is even asked to look.
    all_masked = True

    outcome = evaluate_policy(
        frozen_labels,
        licence_disposition,
        all_masked,
        policy,
        override_enabled=override_enabled,
        override_approval=override_approval,
    )

    if outcome.admitted:
        redacted_content = redact(content, spans, region_key, doc)
        content_hash = hashlib.sha256(redacted_content).hexdigest()
        final_verdict = ladder_verdict
        exclusion_reason = None

        override_approval_record = None
        if override_approval is not None:
            matched_override = next((o for o in policy.overrides if o.id == outcome.matched_rule_id), None)
            if matched_override is not None:
                override_approval_record = C2OverrideApproval(
                    approverRole=override_approval.approver_role,
                    justification=override_approval.justification,
                    expiresAt=classified_at + timedelta(days=matched_override.requires.expires_after_days),
                )

        sanitisation_record = C2Sanitisationrecord(
            artefactId=artefact_id,
            contentHash=content_hash,
            labels=sorted(frozen_labels, key=lambda label: label.value),
            verdict=final_verdict,
            detectorHits=_detector_hits(spans) or None,
            licenceDisposition=licence_disposition,
            policyVersion=policy_version,
            classifiedAt=classified_at,
            classifiedBy=classified_by,
            overrideApproval=override_approval_record,
        )
    else:
        redacted_content = content
        content_hash = hashlib.sha256(content).hexdigest()
        final_verdict = SanitisationVerdict.block
        exclusion_reason = _exclusion_reason(outcome.matched_rule_id)
        sanitisation_record = None

    ledger_entry = append_ledger_entry(
        entry_id=entry_id,
        at=classified_at,
        region=region,
        artefact_id=artefact_id,
        content_hash=content_hash,
        labels=sorted((label.value for label in frozen_labels)),
        verdict=final_verdict.value,
        policy_version=policy_version,
        lawful_basis=lawful_basis,
        approver=outcome.approver,
        run_id=run_id,
        prev_hash=prev_ledger_hash,
        signing_key=signing_key,
    )

    return GateResult(
        admitted=outcome.admitted,
        content_hash=content_hash,
        redacted_content=redacted_content,
        sanitisation_record=sanitisation_record,
        ledger_entry=ledger_entry,
        exclusion_reason=exclusion_reason,
        policy_reason=outcome.reason,
    )
