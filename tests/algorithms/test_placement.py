from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster

from algorithms.placement import PlacementContext, default_placement_context, place, placement_to_contract_value, sole_region
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb


def _cluster(*, regions: list[str], cluster_id: str = "x") -> C6Conceptcluster:
    members = [
        {"attributeId": f"attr://{region}/art-1/Claim.x", "region": region, "role": "core" if i == 0 else "variant", "pairScore": 1.0}
        for i, region in enumerate(regions)
    ]
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": "x",
        "members": members,
        "confidence": 0.9,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    })


def _ctx(**overrides: object) -> PlacementContext:
    base: dict[str, object] = {"max_evidence_tier": lambda cluster: 1}
    base.update(overrides)
    return PlacementContext(**base)  # type: ignore[arg-type]


class TestPlaceRule1:
    def test_three_regions_is_core(self) -> None:
        cluster = _cluster(regions=["us", "uk", "eu"])
        result = place(cluster, _ctx())
        assert result.kind == "core"
        assert result.rule == "1"


class TestPlaceRule2:
    def test_two_regions_defaults_to_extension(self) -> None:
        cluster = _cluster(regions=["uk", "eu"])
        result = place(cluster, _ctx())
        assert result.kind == "extension"
        assert result.rule == "2"
        assert result.region == ("eu", "uk")

    def test_two_regions_with_absence_is_gap_true_is_core(self) -> None:
        cluster = _cluster(regions=["uk", "eu"])
        ctx = _ctx(absence_is_gap=lambda cluster, missing: True)
        result = place(cluster, ctx)
        assert result.kind == "core"
        assert result.rule == "2"
        assert any(f.startswith("gap-in:") for f in result.flags)

    def test_absence_is_gap_receives_the_missing_region(self) -> None:
        cluster = _cluster(regions=["uk", "eu"])
        seen: list[frozenset[str]] = []

        def absence_is_gap(cluster: C6Conceptcluster, missing: frozenset[str]) -> bool:
            seen.append(missing)
            return False

        place(cluster, _ctx(absence_is_gap=absence_is_gap))
        assert seen == [frozenset({"us"})]


class TestPlaceRule3:
    def test_single_region_defaults_to_extension(self) -> None:
        cluster = _cluster(regions=["us"])
        result = place(cluster, _ctx())
        assert result.kind == "extension"
        assert result.rule == "3"
        assert result.region == "us"

    def test_single_region_with_intends_to_close_true_is_core(self) -> None:
        cluster = _cluster(regions=["us"])
        ctx = _ctx(intends_to_close=lambda cluster: True)
        result = place(cluster, ctx)
        assert result.kind == "core"
        assert result.rule == "3"
        assert "planned-adoption" in result.flags


class TestPlaceRule4:
    def test_jurisdictional_regulatory_is_always_extension(self) -> None:
        # Even a 3-region cluster (which would otherwise satisfy Rule 1)
        # is forced to extension by Rule 4 firing first.
        cluster = _cluster(regions=["us", "uk", "eu"])
        ctx = _ctx(is_jurisdictional_regulatory=lambda cluster: True)
        result = place(cluster, ctx)
        assert result.kind == "extension"
        assert result.rule == "4"

    def test_default_is_jurisdictional_regulatory_is_false(self) -> None:
        cluster = _cluster(regions=["us", "uk", "eu"])
        result = place(cluster, _ctx())
        assert result.rule != "4"


class TestPlaceRule5:
    def test_tier_3_evidence_without_workshop_approval_is_extension(self) -> None:
        cluster = _cluster(regions=["us", "uk", "eu"])
        ctx = _ctx(max_evidence_tier=lambda cluster: 3)
        result = place(cluster, ctx)
        assert result.kind == "extension"
        assert result.rule == "5"
        assert "vendorOnly" in result.flags

    def test_tier_3_evidence_with_workshop_approval_falls_through(self) -> None:
        cluster = _cluster(regions=["us", "uk", "eu"])
        ctx = _ctx(max_evidence_tier=lambda cluster: 3, workshop_approved=lambda cluster: True)
        result = place(cluster, ctx)
        assert result.rule == "1"  # falls through to the 3-region rule


class TestSoleRegion:
    def test_single_region(self) -> None:
        cluster = _cluster(regions=["uk"])
        assert sole_region(cluster) == "uk"

    def test_multi_region_is_alphabetically_first(self) -> None:
        cluster = _cluster(regions=["uk", "eu", "us"])
        assert sole_region(cluster) == "eu"


class TestPlacementToContractValue:
    def test_core(self) -> None:
        cluster = _cluster(regions=["us", "uk", "eu"])
        result = place(cluster, _ctx())
        assert placement_to_contract_value(result) == "core"

    def test_single_region_extension(self) -> None:
        cluster = _cluster(regions=["us"])
        result = place(cluster, _ctx())
        assert placement_to_contract_value(result) == "extension:us"

    def test_two_region_extension_picks_alphabetically_first(self) -> None:
        cluster = _cluster(regions=["uk", "eu"])
        result = place(cluster, _ctx())
        assert placement_to_contract_value(result) == "extension:eu"


class TestDefaultPlacementContext:
    def test_max_evidence_tier_reads_real_data(self, tmp_path: Path) -> None:
        run_id = uuid4()
        run_store = RunStore(base_path=tmp_path)
        record = C5Attributerecord.model_validate({
            "attributeId": "attr://us/art-1/Claim.x",
            "runId": str(run_id),
            "region": "us",
            "sourceContract": "art-1",
            "path": "Claim.x",
            "localName": "x",
            "dataType": "string",
            "cardinality": "1..1",
            "obligation": {"level": "mandatory"},
            "evidenceTier": 3,
            "inferred": False,
            "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
        })
        run_store.write_attributes(run_id, "us", [record])
        substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)

        ctx = default_placement_context(substrate, str(run_id))
        cluster = _cluster(regions=["us"])
        assert ctx.max_evidence_tier(cluster) == 3
