from __future__ import annotations

from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.conflict import (
    HOMONYM_SIGNALS,
    classify_conflict,
    contradiction_detected,
    enum_overlap,
    has_absent_in_sibling_region,
    has_mandatory,
    max_pairwise_path_distance,
    min_cut_until,
    pairwise_type_compat,
    split_on_homonym_signals,
)
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import ClusteringConfig

RUN_ID = uuid4()
_CFG = ClusteringConfig()


def _attr(local_name: str, data_type: str, region: str, **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://{region}/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _profiled(local_name: str, data_type: str, region: str = "us", **overrides: object) -> ProfiledAttribute:
    return profile(_attr(local_name, data_type, region, **overrides), siblings=[])


class TestPairwiseTypeCompat:
    def test_same_type_pair_is_one(self) -> None:
        a = _profiled("x", "string")
        b = _profiled("y", "string")
        assert pairwise_type_compat([a, b], _CFG) == [1.0]

    def test_incompatible_pair_is_low(self) -> None:
        a = _profiled("x", "dateTime")
        b = _profiled("y", "string")
        assert pairwise_type_compat([a, b], _CFG)[0] < 0.35


class TestEnumOverlap:
    def test_disjoint_enums_is_zero(self) -> None:
        a = _profiled("x", "string", enumeration=[{"value": "A"}])
        b = _profiled("y", "string", enumeration=[{"value": "B"}])
        assert enum_overlap([a, b]) == 0.0

    def test_identical_enums_is_one(self) -> None:
        a = _profiled("x", "string", enumeration=[{"value": "A"}])
        b = _profiled("y", "string", enumeration=[{"value": "A"}])
        assert enum_overlap([a, b]) == 1.0

    def test_fewer_than_two_enum_members_is_one(self) -> None:
        a = _profiled("x", "string", enumeration=[{"value": "A"}])
        b = _profiled("y", "string")
        assert enum_overlap([a, b]) == 1.0


class TestObligationSignals:
    def test_has_mandatory_true(self) -> None:
        a = _profiled("x", "string", obligation={"level": "mandatory"})
        assert has_mandatory([a]) is True

    def test_has_mandatory_false(self) -> None:
        a = _profiled("x", "string", obligation={"level": "optional"})
        assert has_mandatory([a]) is False

    def test_absent_in_sibling_region_true_when_regions_differ(self) -> None:
        a = _profiled("x", "string", region="uk", obligation={"level": "mandatory"})
        b = _profiled("x", "string", region="eu", obligation={"level": "optional"})
        assert has_absent_in_sibling_region([a, b]) is True

    def test_absent_in_sibling_region_false_when_all_mandatory(self) -> None:
        a = _profiled("x", "string", region="uk", obligation={"level": "mandatory"})
        b = _profiled("x", "string", region="eu", obligation={"level": "mandatory"})
        assert has_absent_in_sibling_region([a, b]) is False


class TestMaxPairwisePathDistance:
    def test_identical_parent_path_is_zero_distance(self) -> None:
        a = _profiled("x", "string", parentPath="Claim")
        b = _profiled("y", "string", parentPath="Claim")
        assert max_pairwise_path_distance([a, b]) == 0.0

    def test_unrelated_parent_paths_is_high_distance(self) -> None:
        a = _profiled("x", "string", parentPath="Claim.Policy")
        b = _profiled("y", "string", parentPath="Endorsement.Vehicle")
        assert max_pairwise_path_distance([a, b]) > 0.8

    def test_single_member_is_zero(self) -> None:
        a = _profiled("x", "string")
        assert max_pairwise_path_distance([a]) == 0.0


class TestContradictionDetected:
    def test_always_false(self) -> None:
        a = _profiled("x", "string")
        assert contradiction_detected([a]) is False


class TestHomonymSignals:
    def test_signal_names_match_spec_taxonomy(self) -> None:
        names = [name for name, _ in HOMONYM_SIGNALS]
        assert names == [
            "type-incompatible",
            "disjoint-enumerations",
            "obligation-inversion",
            "documentation-contradiction",
            "divergent-parent-context",
        ]


class TestSplitOnHomonymSignals:
    def test_no_signal_fires_keeps_one_group(self) -> None:
        a = _profiled("x", "string", parentPath="Claim")
        b = _profiled("y", "string", parentPath="Claim")
        groups = split_on_homonym_signals([a, b], edges={}, config=_CFG)
        assert len(groups) == 1
        assert groups[0].conflict_class is None
        assert set(m.record.attributeId for m in groups[0].members) == {a.record.attributeId, b.record.attributeId}

    def test_type_incompatible_signal_splits_pair(self) -> None:
        a = _attr("claimDate", "dateTime", "uk")
        b = _attr("claimDate", "string", "eu")
        pa, pb = profile(a, siblings=[]), profile(b, siblings=[])
        edges = {frozenset({a.attributeId, b.attributeId}): 0.8}
        groups = split_on_homonym_signals([pa, pb], edges=edges, config=_CFG)
        assert len(groups) == 2
        assert all(g.conflict_class == "homonym" for g in groups)
        assert all(len(g.members) == 1 for g in groups)
        assert "type-incompatible" in (groups[0].conflict_detail or "")

    def test_split_groups_are_singletons_when_no_edges_supplied(self) -> None:
        a = _attr("claimDate", "dateTime", "uk")
        b = _attr("claimDate", "string", "eu")
        pa, pb = profile(a, siblings=[]), profile(b, siblings=[])
        groups = split_on_homonym_signals([pa, pb], edges={}, config=_CFG)
        assert len(groups) == 2


class TestMinCutUntil:
    def test_no_signal_firing_returns_single_group(self) -> None:
        a = _profiled("x", "string")
        b = _profiled("y", "string")
        result = min_cut_until([a, b], edges={}, config=_CFG)
        assert len(result) == 1

    def test_removes_worst_edge_to_separate_three_member_group(self) -> None:
        # a-b incompatible types (fires type-incompatible for the whole
        # group); a-c and b-c are the "worst" (lowest-score) edges, so
        # they get cut first, isolating {a,b} together - which still
        # fires, so a second cut separates a from b too.
        a = _attr("claimDate", "dateTime", "uk")
        b = _attr("claimDate", "string", "eu")
        c = _attr("claimDate", "dateTime", "us")
        pa, pb, pc = profile(a, siblings=[]), profile(b, siblings=[]), profile(c, siblings=[])
        edges = {
            frozenset({a.attributeId, b.attributeId}): 0.9,
            frozenset({a.attributeId, c.attributeId}): 0.85,
            frozenset({b.attributeId, c.attributeId}): 0.1,
        }
        result = min_cut_until([pa, pb, pc], edges=edges, config=_CFG)
        member_id_sets = [frozenset(m.record.attributeId for m in g) for g in result]
        assert frozenset().union(*member_id_sets) == frozenset({a.attributeId, b.attributeId, c.attributeId})
        # every resulting group must itself be signal-free (or a singleton)
        from algorithms.conflict import _any_signal_fires

        for group in result:
            assert len(group) == 1 or not _any_signal_fires(group, _CFG)


class TestClassifyConflict:
    def test_obligation_conflict(self) -> None:
        a = _profiled("x", "string", obligation={"level": "mandatory"})
        b = _profiled("x", "string", obligation={"level": "optional"})
        cls, detail = classify_conflict([a, b], _CFG)
        assert cls == "obligation"
        assert detail is not None

    def test_granularity_conflict(self) -> None:
        a = _profiled("claimant", "object")
        b = _profiled("claimant", "string")
        cls, _ = classify_conflict([a, b], _CFG)
        assert cls == "granularity"

    def test_type_conflict(self) -> None:
        a = _profiled("lossDate", "date")
        b = _profiled("lossDate", "dateTime")
        cls, _ = classify_conflict([a, b], _CFG)
        assert cls == "type"

    def test_enumeration_conflict(self) -> None:
        a = _profiled("status", "string", enumeration=[{"value": "OPEN"}, {"value": "CLOSED"}])
        b = _profiled("status", "string", enumeration=[{"value": "OPEN"}, {"value": "PENDING"}])
        cls, _ = classify_conflict([a, b], _CFG)
        assert cls == "enumeration"

    def test_clean_synonym_returns_none(self) -> None:
        a = _profiled("lossDate", "date")
        b = _profiled("lossDate", "date")
        cls, detail = classify_conflict([a, b], _CFG)
        assert cls is None
        assert detail is None

    def test_single_member_returns_none(self) -> None:
        a = _profiled("x", "string")
        assert classify_conflict([a], _CFG) == (None, None)
