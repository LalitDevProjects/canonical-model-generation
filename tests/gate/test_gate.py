from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from generated.C2.SanitisationRecord._1_0 import LicenceDisposition
from generated.common.defs import ExclusionReason, SanitisationLabel

from contracts.validators import check_i6_ledger_chain_unbroken
from gate.gate import GateResult, classify_and_redact
from gate.policy import OverrideApproval, PolicyDocument, load_policy_document

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
SIGNING_KEY = bytes.fromhex("a" * 64)
REGION_KEY = bytes.fromhex("b" * 64)
AT = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
POLICY = load_policy_document(expected_version=3)
PERMITTED = LicenceDisposition.permitted
PROHIBITED = LicenceDisposition.prohibited
UNKNOWN_DISPOSITION = LicenceDisposition.unknown


def _classify(
    content: bytes,
    *,
    media_type: str = "application/json",
    entry_id: str = "e1",
    artefact_id: str = "art-1",
    region: str = "us",
    licence_disposition: LicenceDisposition = PERMITTED,
    prev_ledger_hash: str | None = None,
    override_enabled: bool = False,
    override_approval: OverrideApproval | None = None,
) -> GateResult:
    return classify_and_redact(
        content=content,
        media_type=media_type,
        entry_id=entry_id,
        artefact_id=artefact_id,
        region=region,
        run_id=RUN_ID,
        licence_disposition=licence_disposition,
        classified_at=AT,
        policy=POLICY,
        policy_version=3,
        lawful_basis="legitimate-interest",
        region_key=REGION_KEY,
        signing_key=SIGNING_KEY,
        prev_ledger_hash=prev_ledger_hash,
        override_enabled=override_enabled,
        override_approval=override_approval,
    )


class TestPurelyStructuralContent:
    def test_admitted_with_allow_verdict_and_unchanged_content(self) -> None:
        content = b'{"claimId": {"type": "string"}}'
        result = _classify(content)
        assert result.admitted is True
        assert result.exclusion_reason is None
        assert result.sanitisation_record is not None
        assert result.sanitisation_record.verdict == "allow"
        assert result.redacted_content == content
        assert result.content_hash == hashlib.sha256(content).hexdigest()
        assert result.ledger_entry.verdict == "allow"


class TestEmptyDocumentFloor:
    """Neither structural_texts, example_texts nor prose_texts (an empty
    JSON object has no keys at all) - the empty-labels safety net in
    classify_and_redact, distinct from the primary "prose exists ->
    DOCUMENTARY" rule, exists purely so C2's labels (min_length=1) never
    receives an empty list."""

    def test_empty_object_still_gets_a_documentary_floor_label_and_is_admitted(self) -> None:
        result = _classify(b"{}")
        assert result.admitted is True
        assert result.sanitisation_record is not None
        assert result.sanitisation_record.labels == [SanitisationLabel.DOCUMENTARY]
        assert result.sanitisation_record.verdict == "allow"


class TestPlantedPersonalDataExample:
    """The Increment 4 acceptance-test fixture shape: the spec's own
    worked tokenise() example values ("A. Smith", "SW1A 1AA")."""

    CONTENT = b'{"claimant": {"type": "string", "example": "A. Smith, SW1A 1AA"}}'

    def test_admitted_with_mask_verdict(self) -> None:
        result = _classify(self.CONTENT, media_type="application/yaml", region="uk")
        assert result.admitted is True
        assert result.sanitisation_record is not None
        assert result.sanitisation_record.verdict == "mask"
        assert SanitisationLabel.SAMPLE_VALUE in result.sanitisation_record.labels
        assert SanitisationLabel.IDENTIFYING in result.sanitisation_record.labels
        assert result.ledger_entry.verdict == "mask"

    def test_raw_values_absent_from_redacted_content(self) -> None:
        result = _classify(self.CONTENT, media_type="application/yaml", region="uk")
        assert b"A. Smith" not in result.redacted_content
        assert b"SW1A 1AA" not in result.redacted_content

    def test_content_hash_is_over_redacted_not_raw_content(self) -> None:
        result = _classify(self.CONTENT, media_type="application/yaml", region="uk")
        assert result.content_hash != hashlib.sha256(self.CONTENT).hexdigest()
        assert result.content_hash == hashlib.sha256(result.redacted_content).hexdigest()


class TestLicenceRestrictedArtefact:
    CONTENT = b'{"claimId": {"type": "string"}}'

    def test_blocked_with_licence_blocked_reason(self) -> None:
        result = _classify(self.CONTENT, licence_disposition=PROHIBITED)
        assert result.admitted is False
        assert result.sanitisation_record is None
        assert result.exclusion_reason == ExclusionReason.licence_blocked
        assert result.ledger_entry.verdict == "block"

    def test_unknown_licence_disposition_also_blocked(self) -> None:
        result = _classify(self.CONTENT, licence_disposition=UNKNOWN_DISPOSITION)
        assert result.admitted is False
        assert result.exclusion_reason == ExclusionReason.licence_blocked

    def test_licence_block_wins_even_though_ladder_alone_would_allow(self) -> None:
        # The two-tier reconciliation's own critical case: purely
        # STRUCTURAL content ladder-allows on its own, but a prohibited
        # licence disposition must still force the final verdict to
        # block - this is exactly the bug caught in gate/policy.py's own
        # evaluate_policy (allow-structural listed before block-unlicensed
        # in policy.yaml).
        result = _classify(self.CONTENT, licence_disposition=PROHIBITED)
        assert result.ledger_entry.verdict == "block"


class TestSensitiveDomainContent:
    CONTENT = b'{"note": {"description": "Claimant diagnosis: psychiatric review pending."}}'

    def test_blocked_with_policy_blocked_reason(self) -> None:
        result = _classify(self.CONTENT)
        assert result.admitted is False
        assert result.sanitisation_record is None
        assert result.exclusion_reason == ExclusionReason.policy_blocked
        assert result.ledger_entry.verdict == "block"


class TestDpoOverride:
    """gate/policy.py's evaluate_policy only reaches the override path when
    NO rule matched at all (neither block nor allow) - Section 5.4's own
    overrides mechanism is for the "matches no rule" gap, not a way to
    bypass an explicit block-unlicensed/block-personal verdict. With
    policy.yaml's actual rule set (allow-documentary-masked's subset
    covers every reachable label combination that isn't already caught by
    block-personal, and all_masked is always true by construction - see
    gate/gate.py's classify_and_redact), that "no rule matched" gap is
    never reached through this orchestrator; override reachability itself
    is exercised directly at the policy layer (tests/gate/test_policy.py).
    What matters here, and is the real regression risk, is the negative:
    an override must never silently defeat an explicit block."""

    CONTENT = b'{"claimId": {"type": "string"}}'

    def test_override_does_not_bypass_an_explicit_licence_block(self) -> None:
        result = _classify(
            self.CONTENT,
            licence_disposition=PROHIBITED,
            override_enabled=True,
            override_approval=OverrideApproval(approver_role="DPO", justification="approved for audit"),
        )
        assert result.admitted is False
        assert result.exclusion_reason == ExclusionReason.licence_blocked

    def test_override_not_applied_when_not_enabled(self) -> None:
        result = _classify(
            self.CONTENT,
            licence_disposition=PROHIBITED,
            override_enabled=False,
            override_approval=OverrideApproval(approver_role="DPO", justification="approved for audit"),
        )
        assert result.admitted is False


class TestDpoOverrideWiringWhenReachable:
    """Proves classify_and_redact's own override_approval_record
    construction (C2Sanitisationrecord.overrideApproval, including the
    computed expiresAt) is correct when the override path IS reached -
    exercised against a deliberately minimal policy document (no rules at
    all, so nothing admits except via the override), since policy.yaml's
    own rule set never lets classify_and_redact reach that path (see
    TestDpoOverride's docstring)."""

    NO_RULES_POLICY = PolicyDocument.model_validate({
        "version": 1,
        "default": "block",
        "rules": [],
        "overrides": [{
            "id": "dpo-approved-exception",
            "requires": {"approver_role": "DPO", "justification": "required", "expires_after_days": 30},
            "effect": "allow",
            "audit": "mandatory",
        }],
    })

    def test_override_admits_and_records_approval_with_computed_expiry(self) -> None:
        content = b'{"claimId": {"type": "string"}}'
        result = classify_and_redact(
            content=content, media_type="application/json", entry_id="e1", artefact_id="art-1",
            region="us", run_id=RUN_ID, licence_disposition=PERMITTED, classified_at=AT,
            policy=self.NO_RULES_POLICY, policy_version=1, lawful_basis="legitimate-interest",
            region_key=REGION_KEY, signing_key=SIGNING_KEY, prev_ledger_hash=None,
            override_enabled=True,
            override_approval=OverrideApproval(approver_role="DPO", justification="approved for audit"),
        )
        assert result.admitted is True
        assert result.sanitisation_record is not None
        approval = result.sanitisation_record.overrideApproval
        assert approval is not None
        assert approval.approverRole == "DPO"
        assert approval.justification == "approved for audit"
        assert (approval.expiresAt - AT).days == 30
        assert result.ledger_entry.approver == "DPO"

    def test_no_matching_rule_and_no_override_falls_through_to_default_block(self) -> None:
        content = b'{"claimId": {"type": "string"}}'
        result = classify_and_redact(
            content=content, media_type="application/json", entry_id="e1", artefact_id="art-1",
            region="us", run_id=RUN_ID, licence_disposition=PERMITTED, classified_at=AT,
            policy=self.NO_RULES_POLICY, policy_version=1, lawful_basis="legitimate-interest",
            region_key=REGION_KEY, signing_key=SIGNING_KEY, prev_ledger_hash=None,
        )
        assert result.admitted is False
        assert result.exclusion_reason == ExclusionReason.policy_blocked


class TestLedgerChaining:
    def test_two_sequential_calls_produce_a_verifiable_chain(self) -> None:
        content_a = b'{"claimId": {"type": "string"}}'
        content_b = b'{"lossDate": {"type": "string"}}'
        result_a = _classify(content_a, entry_id="e1", artefact_id="art-1")
        result_b = _classify(
            content_b, entry_id="e2", artefact_id="art-2", prev_ledger_hash=str(result_a.ledger_entry.hash),
        )
        violations = check_i6_ledger_chain_unbroken(
            [result_a.ledger_entry, result_b.ledger_entry], signing_key=SIGNING_KEY,
        )
        assert violations == []

    def test_a_blocked_artefact_still_gets_a_ledger_entry(self) -> None:
        content = b'{"claimId": {"type": "string"}}'
        result = _classify(content, licence_disposition=PROHIBITED)
        assert result.ledger_entry.entryId == "e1"
        assert check_i6_ledger_chain_unbroken([result.ledger_entry], signing_key=SIGNING_KEY) == []
