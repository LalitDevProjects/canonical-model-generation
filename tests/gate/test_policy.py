from __future__ import annotations

import pytest

from generated.C2.SanitisationRecord._1_0 import LicenceDisposition
from generated.common.defs import SanitisationLabel

from gate.policy import OverrideApproval, evaluate_policy, load_policy_document

STRUCTURAL = SanitisationLabel.STRUCTURAL
DOCUMENTARY = SanitisationLabel.DOCUMENTARY
IDENTIFYING = SanitisationLabel.IDENTIFYING
SAMPLE_VALUE = SanitisationLabel.SAMPLE_VALUE
PERSONAL_DATA = SanitisationLabel.PERSONAL_DATA
SENSITIVE_DOMAIN = SanitisationLabel.SENSITIVE_DOMAIN

PERMITTED = LicenceDisposition.permitted
PROHIBITED = LicenceDisposition.prohibited
UNKNOWN_DISPOSITION = LicenceDisposition.unknown


def test_policy_document_loads_and_matches_config_version() -> None:
    policy = load_policy_document(expected_version=3)
    assert policy.version == 3
    assert policy.default == "block"
    assert [r.id for r in policy.rules] == [
        "allow-structural", "allow-documentary-masked", "block-personal", "block-unlicensed",
    ]


def test_load_policy_document_rejects_version_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        load_policy_document(expected_version=99)


class TestAllowStructural:
    def test_purely_structural_labels_admitted(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL}), PERMITTED, True, policy)
        assert outcome.admitted is True
        assert outcome.matched_rule_id == "allow-structural"


class TestAllowDocumentaryMasked:
    def test_admitted_when_all_masked(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL, DOCUMENTARY, IDENTIFYING, SAMPLE_VALUE}), PERMITTED, True, policy)
        assert outcome.admitted is True
        assert outcome.matched_rule_id == "allow-documentary-masked"

    def test_not_admitted_when_not_all_masked(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL, IDENTIFYING}), PERMITTED, False, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "<default>"


class TestBlockPersonal:
    def test_sensitive_domain_label_blocks(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({SENSITIVE_DOMAIN}), PERMITTED, True, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-personal"
        assert outcome.reason == "Personal or special-category data never crosses a border."

    def test_personal_data_label_blocks(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({PERSONAL_DATA}), PERMITTED, True, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-personal"


class TestBlockUnlicensed:
    def test_prohibited_licence_blocks(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL}), PROHIBITED, True, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-unlicensed"

    def test_unknown_licence_blocks(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL}), UNKNOWN_DISPOSITION, True, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-unlicensed"

    def test_block_wins_over_an_also_matching_allow_rule_regardless_of_list_order(self) -> None:
        # allow-structural is listed BEFORE block-unlicensed in policy.yaml
        # and would match first under naive first-match-wins evaluation -
        # this is the exact bug caught during implementation (see
        # evaluate_policy's own docstring).
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({STRUCTURAL}), PROHIBITED, True, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-unlicensed"


class TestDefaultBlockFallback:
    def test_no_matching_rule_defaults_to_block(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({IDENTIFYING}), PERMITTED, False, policy)
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "<default>"


class TestDpoOverride:
    def test_override_admits_when_enabled_and_approved(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(
            frozenset({IDENTIFYING}), PERMITTED, False, policy,
            override_enabled=True, override_approval=OverrideApproval("DPO", "reviewed and approved"),
        )
        assert outcome.admitted is True
        assert outcome.matched_rule_id == "dpo-approved-exception"
        assert outcome.approver == "DPO"

    def test_override_ignored_when_disabled(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(
            frozenset({IDENTIFYING}), PERMITTED, False, policy,
            override_enabled=False, override_approval=OverrideApproval("DPO", "reviewed and approved"),
        )
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "<default>"

    def test_override_ignored_without_an_approval(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(frozenset({IDENTIFYING}), PERMITTED, False, policy, override_enabled=True, override_approval=None)
        assert outcome.admitted is False

    def test_override_rejected_for_wrong_approver_role(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(
            frozenset({IDENTIFYING}), PERMITTED, False, policy,
            override_enabled=True, override_approval=OverrideApproval("Manager", "reviewed"),
        )
        assert outcome.admitted is False

    def test_override_rejected_for_empty_justification(self) -> None:
        policy = load_policy_document()
        outcome = evaluate_policy(
            frozenset({IDENTIFYING}), PERMITTED, False, policy,
            override_enabled=True, override_approval=OverrideApproval("DPO", "   "),
        )
        assert outcome.admitted is False

    def test_override_does_not_apply_when_a_rule_already_matched(self) -> None:
        # Override is only reached via the default-block fallback, never
        # overrides an explicit rule match (e.g. block-personal).
        policy = load_policy_document()
        outcome = evaluate_policy(
            frozenset({SENSITIVE_DOMAIN}), PERMITTED, True, policy,
            override_enabled=True, override_approval=OverrideApproval("DPO", "reviewed"),
        )
        assert outcome.admitted is False
        assert outcome.matched_rule_id == "block-personal"
