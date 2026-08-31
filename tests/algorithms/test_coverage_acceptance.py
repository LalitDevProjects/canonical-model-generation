"""
Increment 8's literal acceptance test (Section 17.2): "Coverage is
computed with a published denominator; Gate 1 blocks correctly on a
seeded unresolved mandatory attribute." Runs entirely against the real
golden/coverage/*.json fixtures (hand-authored real C5/C6/C8 shapes,
model_validate-loaded - the same precedent Increment 5's own
substrate/graph_fixture.json set, since clusters/candidates are
themselves synthesized artefacts with no "raw" source format to parse
them from) through the real build_universe() -> coverage() ->
gap_register() path - zero LLM, zero DB, matching every prior
increment's own "the deterministic pipeline alone satisfies the
acceptance test" precedent.

golden/coverage/clusters.json plants exactly the acceptance test's own
scenario: cluster://claim-id (3 regions, a ratified candidate) resolves
cleanly to "core"; cluster://loss-date is a weight-5 (mandatory) concept
with NO candidate synthesized at all - the seeded unresolved mandatory
attribute Gate 1 must block on. cluster://reserve-amount has a candidate
that is not yet ratified, exercising Gate 3/"unevidenced" alongside it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.common.defs import ExclusionEntry

from algorithms.coverage import build_universe, coverage, gap_register
from config.settings import load_settings
from contracts.validators import check_i4_coverage_scored_attributes_evidenced, unwrap_ref
from substrate.api import SubstrateApi

GOLDEN_COVERAGE_DIR = Path(__file__).resolve().parents[2] / "golden" / "coverage"
RUN_ID = UUID("00000000-0000-0000-0000-000000000008")


class _GoldenSubstrateApi:
    """No DB/RunStore needed - build_universe() only ever calls
    get_attribute(), and the golden attribute set is small and fully
    known upfront."""

    def __init__(self, records: list[C5Attributerecord]) -> None:
        self._by_id = {r.attributeId: r for r in records}

    def get_attribute(self, run_id: str, attribute_id: str) -> C5Attributerecord:
        return self._by_id[attribute_id]


def _load(name: str) -> Any:
    return json.loads((GOLDEN_COVERAGE_DIR / name).read_text(encoding="utf-8"))


class TestCoverageIsComputedWithAPublishedDenominatorAndGate1Blocks:
    def test_acceptance(self) -> None:
        attributes = [C5Attributerecord.model_validate(a) for a in _load("attributes.json")]
        clusters = [C6Conceptcluster.model_validate(c) for c in _load("clusters.json")]
        candidates = [C8Canonicalcandidate.model_validate(c) for c in _load("candidates.json")]
        exclusions = [ExclusionEntry.model_validate(e) for e in _load("exclusions.json")]

        candidates_by_cluster_id = {
            str(unwrap_ref(ref)): candidate for candidate in candidates for ref in candidate.clusterRefs
        }
        substrate = cast(SubstrateApi, _GoldenSubstrateApi(attributes))
        config = load_settings().coverage

        universe = build_universe(clusters, candidates_by_cluster_id, substrate=substrate, run_id=str(RUN_ID))
        report = coverage(universe, "claims", exclusions=exclusions, config=config)
        gaps = gap_register(universe, report, exclusions=exclusions, config=config)

        # Clause 1: "Coverage is computed with a published denominator."
        assert report.denominator == len(universe) == 3
        assert len(report.exclusions) == 1
        assert str(report.exclusions[0].uri) == "git://legacy-claims-v0/spec.yaml"

        # Clause 2: "Gate 1 blocks correctly on a seeded unresolved
        # mandatory attribute."
        assert report.gate1Pass is False
        unresolved_ids = {g.conceptId for g in gaps if g.reason == "unresolved"}
        assert "cluster://loss-date" in unresolved_ids

        # The clean, 3-region, ratified concept must NOT itself be flagged unresolved.
        assert "canon://Claim.claimId" not in unresolved_ids

        # Gate 3 also correctly reflects the unratified candidate.
        assert report.gate3Pass is False
        unevidenced_ids = {g.conceptId for g in gaps if g.reason == "unevidenced"}
        assert "canon://Claim.reserveAmount" in unevidenced_ids

        # The excluded corpus artefact surfaces in the gap register too.
        assert any(g.reason == "excluded" for g in gaps)

        # Invariant I4 (pre-built at Increment 1, anticipating exactly
        # this algorithm) independently agrees with coverage()'s own
        # "unevidenced" classification - genuinely exercised for the
        # first time here.
        scored_attributes: list[dict[str, object]] = [
            {"conceptId": c.concept_id, "evidenceRefs": list(c.evidence_refs), "ratifyingSme": c.ratifying_sme}
            for c in universe
        ]
        i4_violations = check_i4_coverage_scored_attributes_evidenced(report, scored_attributes)
        i4_flagged_ids = {v.record_id.split(":", 1)[1] for v in i4_violations}
        expected_unevidenced = {c.concept_id for c in universe if not c.evidence_refs or not c.ratifying_sme}
        assert i4_flagged_ids == expected_unevidenced
        # gap_register's own "unevidenced" entries are the subset not
        # already reported as "unresolved" - never double-reported.
        assert unevidenced_ids <= expected_unevidenced
