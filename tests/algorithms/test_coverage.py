from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.common.defs import ExclusionEntry, Level

from algorithms.coverage import Concept, build_universe, coverage, gap_register, strongest_obligation, weakest_obligation, weight_from_obligation
from config.settings import CoverageConfig
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb

RUN_ID = uuid4()
_CFG = CoverageConfig()


def _attr(local_name: str, region: str, *, obligation: str = "mandatory", tier: int = 1, inferred: bool = False) -> C5Attributerecord:
    return C5Attributerecord.model_validate({
        "attributeId": f"attr://{region}/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": "string",
        "cardinality": "1..1",
        "obligation": {"level": obligation},
        "evidenceTier": tier,
        "inferred": inferred,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x"],
    })


def _cluster(cluster_id: str, member_ids: list[tuple[str, str]]) -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": cluster_id,
        "members": [
            {"attributeId": aid, "region": region, "role": "core" if i == 0 else "variant", "pairScore": 1.0}
            for i, (aid, region) in enumerate(member_ids)
        ],
        "confidence": 0.9,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


def _candidate(
    candidate_id: str, cluster_id: str, *, placement: str = "core", weight: int = 5,
    ratification_status: str = "pending", sme: str | None = None,
) -> C8Canonicalcandidate:
    return C8Canonicalcandidate.model_validate({
        "candidateId": f"canon://{candidate_id}",
        "entity": "Claim",
        "attribute": candidate_id,
        "dataType": "string",
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "placement": placement,
        "placementRule": "1",
        "namingSource": "derived",
        "rationale": "x",
        "clusterRefs": [f"cluster://{cluster_id}"],
        "weight": weight,
        "ratification": {"status": ratification_status, "sme": sme, "decidedAt": None},
    })


class TestWeightFromObligation:
    def test_mandatory_is_5(self) -> None:
        assert weight_from_obligation(Level.mandatory) == 5

    def test_conditional_is_3(self) -> None:
        assert weight_from_obligation(Level.conditional) == 3

    def test_optional_is_1(self) -> None:
        assert weight_from_obligation(Level.optional) == 1


class TestStrongestObligation:
    def test_picks_the_strongest_across_records(self) -> None:
        records = [_attr("x", "us", obligation="optional"), _attr("y", "uk", obligation="mandatory")]
        assert strongest_obligation(records) == Level.mandatory

    def test_empty_defaults_to_optional(self) -> None:
        assert strongest_obligation([]) == Level.optional


class TestWeakestObligation:
    def test_picks_the_weakest_across_records(self) -> None:
        records = [_attr("x", "us", obligation="mandatory"), _attr("y", "uk", obligation="optional")]
        assert weakest_obligation(records) == Level.optional

    def test_empty_defaults_to_optional(self) -> None:
        assert weakest_obligation([]) == Level.optional


class TestBuildUniverse:
    def test_candidate_present_resolves_to_core(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        record = _attr("claimId", "us")
        run_store.write_attributes(RUN_ID, "us", [record])
        substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)

        cluster = _cluster("claim-id", [(record.attributeId, "us")])
        candidate = _candidate("Claim.claimId", "claim-id", placement="core", ratification_status="approved", sme="jane@example.com")

        universe = build_universe([cluster], {"cluster://claim-id": candidate}, substrate=substrate, run_id=str(RUN_ID))

        assert len(universe) == 1
        assert universe[0].resolution == "core"
        assert universe[0].ratifying_sme == "jane@example.com"
        assert universe[0].weight == 5

    def test_extension_placement_collapses_to_extension_resolution(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        record = _attr("x", "us")
        run_store.write_attributes(RUN_ID, "us", [record])
        substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
        cluster = _cluster("x", [(record.attributeId, "us")])
        candidate = _candidate("Claim.x", "x", placement="extension:us")

        universe = build_universe([cluster], {"cluster://x": candidate}, substrate=substrate, run_id=str(RUN_ID))
        assert universe[0].resolution == "extension"

    def test_no_candidate_resolves_to_gap_with_obligation_derived_weight(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        record = _attr("lossDate", "us", obligation="mandatory")
        run_store.write_attributes(RUN_ID, "us", [record])
        substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
        cluster = _cluster("loss-date", [(record.attributeId, "us")])

        universe = build_universe([cluster], {}, substrate=substrate, run_id=str(RUN_ID))

        assert len(universe) == 1
        assert universe[0].resolution == "gap"
        assert universe[0].weight == 5
        assert universe[0].ratifying_sme is None

    def test_unratified_candidate_has_no_ratifying_sme(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        record = _attr("x", "us")
        run_store.write_attributes(RUN_ID, "us", [record])
        substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
        cluster = _cluster("x", [(record.attributeId, "us")])
        candidate = _candidate("Claim.x", "x", ratification_status="pending")

        universe = build_universe([cluster], {"cluster://x": candidate}, substrate=substrate, run_id=str(RUN_ID))
        assert universe[0].ratifying_sme is None


def _concept(
    concept_id: str, *, weight: int = 5, resolution: str = "core", evidence_refs: tuple[str, ...] = ("evref://us/git/art-1@1234567890abcdef#/x",),
    ratifying_sme: str | None = "jane@example.com", regions: frozenset[str] = frozenset({"us"}), inferred: bool = False,
) -> Concept:
    return Concept(
        concept_id=concept_id, weight=weight, evidence_refs=evidence_refs,  # type: ignore[arg-type]
        ratifying_sme=ratifying_sme, resolution=resolution, regions=regions, inferred=inferred,  # type: ignore[arg-type]
    )


class TestCoverage:
    def test_empty_universe_scores_zero(self) -> None:
        report = coverage([], "claims", config=_CFG)
        assert report.score == 0.0
        assert report.denominator == 0

    def test_fully_resolved_core_universe_scores_one(self) -> None:
        universe = [_concept("a", regions=frozenset({"us", "uk", "eu"}))]
        report = coverage(universe, "claims", config=_CFG)
        assert report.score == 1.0
        assert report.gate1Pass is True
        assert report.gate3Pass is True

    def test_gate1_blocks_on_seeded_unresolved_mandatory_concept(self) -> None:
        universe = [_concept("a", weight=5, resolution="gap", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.gate1Pass is False

    def test_gate1_ignores_non_mandatory_unresolved_concepts(self) -> None:
        universe = [_concept("a", weight=3, resolution="gap", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.gate1Pass is True

    def test_gate3_fails_when_evidence_refs_empty(self) -> None:
        universe = [_concept("a", evidence_refs=())]
        report = coverage(universe, "claims", config=_CFG)
        assert report.gate3Pass is False

    def test_gate3_fails_when_unratified(self) -> None:
        universe = [_concept("a", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.gate3Pass is False

    def test_unresolved_concept_stays_in_denominator(self) -> None:
        universe = [_concept("a", weight=5, resolution="gap", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.denominator == 1
        assert report.weightSum == 5

    def test_gate2_requires_domain_target_and_region_floor(self) -> None:
        universe = [_concept("a", regions=frozenset({"us", "uk", "eu"}))]
        report = coverage(universe, "claims", config=_CFG)
        assert report.gate2Pass is True
        universe_low = [_concept("a", resolution="extension", regions=frozenset({"us", "uk", "eu"}))]
        report_low = coverage(universe_low, "claims", config=_CFG)
        assert report_low.gate2Pass is False

    def test_per_region_only_counts_concepts_present_in_that_region(self) -> None:
        universe = [_concept("a", regions=frozenset({"us"})), _concept("b", regions=frozenset({"uk"}))]
        report = coverage(universe, "claims", config=_CFG)
        assert report.perRegion.us == 1.0
        assert report.perRegion.uk == 1.0
        assert report.perRegion.eu == 0.0

    def test_specified_vs_inferred_split(self) -> None:
        universe = [_concept("a", inferred=False), _concept("b", inferred=True)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.specifiedVsInferred.specified == 1
        assert report.specifiedVsInferred.inferred == 1

    def test_exclusions_are_published_alongside_the_score(self) -> None:
        exclusion = ExclusionEntry.model_validate({"uri": "git://x/y", "reason": "out-of-domain", "decidedBy": "policy"})
        report = coverage([], "claims", exclusions=[exclusion], config=_CFG)
        assert len(report.exclusions) == 1
        assert str(report.exclusions[0].uri) == "git://x/y"

    def test_denominator_matches_universe_length_regardless_of_gates(self) -> None:
        universe = [_concept(f"c{i}", resolution="gap", ratifying_sme=None) for i in range(4)]
        report = coverage(universe, "claims", config=_CFG)
        assert report.denominator == 4


class TestGapRegister:
    def test_unresolved_mandatory_concept_produces_unresolved_entry(self) -> None:
        universe = [_concept("a", weight=5, resolution="gap", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        reasons = {e.reason for e in entries}
        assert "unresolved" in reasons

    def test_unresolved_concept_not_double_reported_as_unevidenced(self) -> None:
        universe = [_concept("a", weight=5, resolution="gap", ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        assert sum(1 for e in entries if e.conceptId == "a" and e.reason == "unevidenced") == 0

    def test_unevidenced_non_mandatory_concept_produces_unevidenced_entry(self) -> None:
        universe = [_concept("a", weight=3, ratifying_sme=None)]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        assert any(e.reason == "unevidenced" and e.conceptId == "a" for e in entries)

    def test_below_region_floor_entry_for_non_core_concept(self) -> None:
        universe = [_concept("a", resolution="extension", regions=frozenset({"us"}))]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        assert any(e.reason == "below-region-floor" for e in entries)

    def test_core_concept_not_flagged_below_region_floor(self) -> None:
        universe = [_concept("a", resolution="core", regions=frozenset({"us"})), _concept("b", resolution="extension", regions=frozenset({"us"}))]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        assert not any(e.reason == "below-region-floor" and e.conceptId == "a" for e in entries)

    def test_excluded_entry_produced_from_exclusions(self) -> None:
        exclusion = ExclusionEntry.model_validate({"uri": "git://x/y", "reason": "out-of-domain", "decidedBy": "policy"})
        universe: list[Concept] = []
        report = coverage(universe, "claims", exclusions=[exclusion], config=_CFG)
        entries = gap_register(universe, report, exclusions=[exclusion], config=_CFG)
        assert any(e.reason == "excluded" and e.conceptId == "git://x/y" for e in entries)

    def test_clean_universe_produces_no_gap_entries(self) -> None:
        universe = [_concept("a", regions=frozenset({"us", "uk", "eu"}))]
        report = coverage(universe, "claims", config=_CFG)
        entries = gap_register(universe, report, config=_CFG)
        assert entries == []
