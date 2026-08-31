"""
Policy decision point (Section 5.4). Policy is loaded from gate/policy.yaml
- a transcription of the spec's own YAML, kept in its own versioned file
rather than a config/platform.yaml section (Section 5.4's own framing:
"Policy is data, not code. It is versioned alongside the platform" implies
an independently reviewable artefact, not a subsection of unrelated
platform settings).

This module implements the POLICY tier of the two-tier verdict model (see
gate/gate.py's module docstring for the full reconciliation): it decides
admit vs. reject for CorpusManifest inclusion, evaluated against the
accumulated labels + licence disposition + whether every mask-worthy span
was actually masked. It does NOT decide the ladder's own allow/mask
distinction for an admitted artefact - that's computed directly from
detector output (gate/detectors.py), independently.

"default: block is not negotiable: an artefact that matches no rule MUST
NOT cross." - a policy document with no matching rule falls through to
reject, unless the DPO override path (gate.dpo_override.enabled) admits it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from generated.C2.SanitisationRecord._1_0 import LicenceDisposition
from generated.common.defs import SanitisationLabel

DEFAULT_POLICY_YAML = Path(__file__).resolve().parent / "policy.yaml"


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels_all_in: list[SanitisationLabel] | None = None
    labels_subset_of: list[SanitisationLabel] | None = None
    labels_any_in: list[SanitisationLabel] | None = None
    licence_disposition_in: list[LicenceDisposition] | None = None
    all_masked: bool | None = None


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    when: RuleCondition
    verdict: Literal["allow", "block"]
    reason: str | None = None


class OverrideRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_role: str
    justification: Literal["required"]
    expires_after_days: int


class PolicyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    requires: OverrideRequirement
    effect: Literal["allow"]
    audit: Literal["mandatory"]


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    default: Literal["block"]
    rules: list[PolicyRule]
    overrides: list[PolicyOverride] = Field(default_factory=list)


def load_policy_document(path: Path | None = None, *, expected_version: int | None = None) -> PolicyDocument:
    """expected_version, when given, MUST match the loaded document's own
    version - operationalizes "keeping [config.egress.policy_version and
    the policy document] in sync" as a real fail-closed check, not just a
    comment."""
    raw: dict[str, Any] = yaml.safe_load((path or DEFAULT_POLICY_YAML).read_text())
    document = PolicyDocument.model_validate(raw)
    if expected_version is not None and document.version != expected_version:
        raise ValueError(
            f"gate policy document version {document.version} does not match "
            f"config.egress.policy_version {expected_version}"
        )
    return document


@dataclass(frozen=True)
class OverrideApproval:
    approver_role: str
    justification: str


@dataclass(frozen=True)
class PolicyOutcome:
    admitted: bool
    matched_rule_id: str
    reason: str | None
    approver: str | None = None


def _condition_matches(
    condition: RuleCondition,
    labels: frozenset[SanitisationLabel],
    licence_disposition: LicenceDisposition,
    all_masked: bool,
) -> bool:
    """labels_all_in and labels_subset_of are the same subset check
    (labels is-a-subset-of the configured set) - the policy YAML uses both
    spellings across different rules for readability, not because they
    differ semantically; both are implemented identically here."""
    if condition.labels_all_in is not None and not labels.issubset(set(condition.labels_all_in)):
        return False
    if condition.labels_subset_of is not None and not labels.issubset(set(condition.labels_subset_of)):
        return False
    if condition.labels_any_in is not None and labels.isdisjoint(set(condition.labels_any_in)):
        return False
    if condition.licence_disposition_in is not None and licence_disposition not in condition.licence_disposition_in:
        return False
    if condition.all_masked is not None and condition.all_masked != all_masked:
        return False
    return True


def _override_valid(override: PolicyOverride, approval: OverrideApproval) -> bool:
    if approval.approver_role != override.requires.approver_role:
        return False
    if override.requires.justification == "required" and not approval.justification.strip():
        return False
    return True


def evaluate_policy(
    labels: frozenset[SanitisationLabel],
    licence_disposition: LicenceDisposition,
    all_masked: bool,
    policy: PolicyDocument,
    *,
    override_enabled: bool = False,
    override_approval: OverrideApproval | None = None,
) -> PolicyOutcome:
    """Evaluates every rule (not first-match-wins in list order) and lets
    any matching BLOCK rule win over any matching ALLOW rule - Section
    5.1's "verdict precedence is block > mask > allow" applies at this
    layer too, not only to the ladder's own rung hits.

    This matters concretely: the spec's own policy.yaml lists
    allow-structural before block-unlicensed. An artefact with purely
    STRUCTURAL labels but a prohibited licence disposition matches BOTH
    rules - first-match-wins-by-list-order would incorrectly admit it via
    allow-structural, silently skipping the L5 licence check the golden
    corpus's own acceptance test depends on. Block-wins-regardless-of-order
    is the only reading consistent with "a single L4 or L5 hit blocks the
    entire artefact" (Section 5.1) and was caught by testing this function
    against exactly that case, not inferred from the prose alone.
    """
    matched_block: PolicyRule | None = None
    matched_allow: PolicyRule | None = None
    for rule in policy.rules:
        if not _condition_matches(rule.when, labels, licence_disposition, all_masked):
            continue
        if rule.verdict == "block" and matched_block is None:
            matched_block = rule
        elif rule.verdict == "allow" and matched_allow is None:
            matched_allow = rule

    if matched_block is not None:
        return PolicyOutcome(admitted=False, matched_rule_id=matched_block.id, reason=matched_block.reason)
    if matched_allow is not None:
        return PolicyOutcome(admitted=True, matched_rule_id=matched_allow.id, reason=matched_allow.reason)

    if override_enabled and override_approval is not None:
        for override in policy.overrides:
            if _override_valid(override, override_approval):
                return PolicyOutcome(
                    admitted=True,
                    matched_rule_id=override.id,
                    reason="dpo-approved-exception",
                    approver=override_approval.approver_role,
                )

    return PolicyOutcome(
        admitted=False,
        matched_rule_id="<default>",
        reason="no policy rule matched; default-block fallback applied",
    )
