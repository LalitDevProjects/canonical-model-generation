from __future__ import annotations

from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.profiling import ProfiledAttribute, profile
from algorithms.similarity import (
    compute_embeddings,
    constraint_overlap,
    cosine,
    jaccard,
    path_similarity,
    pattern_range_similarity,
    similarity,
    type_compatibility,
)
from config.settings import ClusteringConfig

RUN_ID = uuid4()
_CFG = ClusteringConfig()


def _attr(local_name: str, data_type: str, **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://us/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": "us",
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _profiled(local_name: str, data_type: str, **overrides: object) -> ProfiledAttribute:
    return profile(_attr(local_name, data_type, **overrides), siblings=[])


class TestCosine:
    def test_identical_vectors(self) -> None:
        assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors(self) -> None:
        assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_empty_vector_is_zero(self) -> None:
        assert cosine([], [1.0]) == 0.0
        assert cosine([1.0], []) == 0.0

    def test_zero_vector_is_zero(self) -> None:
        assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestJaccard:
    def test_both_empty_is_zero(self) -> None:
        assert jaccard(set(), set()) == 0.0

    def test_disjoint_is_zero(self) -> None:
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_identical_is_one(self) -> None:
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_partial_overlap(self) -> None:
        assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3


class TestPathSimilarity:
    def test_none_path_is_zero(self) -> None:
        assert path_similarity(None, "Claim") == 0.0
        assert path_similarity("Claim", None) == 0.0

    def test_identical_path_is_one(self) -> None:
        assert path_similarity("Claim", "Claim") == 1.0

    def test_partial_path_overlap(self) -> None:
        assert path_similarity("Claim.Claimant", "Claim.Policy") == 1 / 3


class TestTypeCompatibility:
    def test_same_type_is_one_even_when_unlisted(self) -> None:
        assert type_compatibility(_CFG, "integer", "integer") == 1.0

    def test_configured_pair(self) -> None:
        assert type_compatibility(_CFG, "date", "dateTime") == 0.85
        assert type_compatibility(_CFG, "dateTime", "date") == 0.85  # order-independent

    def test_unlisted_divergent_pair_is_zero(self) -> None:
        assert type_compatibility(_CFG, "dateTime", "string") == 0.0


class TestPatternRangeSimilarity:
    def test_neither_side_declares_is_neutral(self) -> None:
        assert pattern_range_similarity([], []) == 0.5

    def test_only_one_side_declares(self) -> None:
        a = _attr("x", "string", constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}]).constraints
        assert pattern_range_similarity(a or [], []) == 0.3

    def test_no_shared_kind_is_zero(self) -> None:
        a = _attr("x", "string", constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}]).constraints
        b = _attr("y", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        assert pattern_range_similarity(a or [], b or []) == 0.0

    def test_identical_pattern_is_one(self) -> None:
        a = _attr("x", "string", constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}]).constraints
        b = _attr("y", "string", constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}]).constraints
        assert pattern_range_similarity(a or [], b or []) == 1.0

    def test_different_pattern_is_zero(self) -> None:
        a = _attr("x", "string", constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}]).constraints
        b = _attr("y", "string", constraints=[{"kind": "pattern", "expression": "^[a-z]+$"}]).constraints
        assert pattern_range_similarity(a or [], b or []) == 0.0

    def test_overlapping_range_scores_between_zero_and_one(self) -> None:
        a = _attr(
            "x", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}, {"kind": "range", "expression": "maximum=10"}]
        ).constraints
        b = _attr(
            "y", "integer", constraints=[{"kind": "range", "expression": "minimum=5"}, {"kind": "range", "expression": "maximum=15"}]
        ).constraints
        score = pattern_range_similarity(a or [], b or [])
        assert 0.0 < score < 1.0

    def test_identical_unbounded_range_is_one(self) -> None:
        # Both sides declare only "minimum=0" (no maximum) - identical
        # open-ended constraints, not "negligible overlap in an infinite
        # union".
        a = _attr("x", "decimal", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        assert pattern_range_similarity(a or [], a or []) == 1.0

    def test_one_bounded_one_unbounded_range_is_low(self) -> None:
        a = _attr("x", "decimal", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        b = _attr(
            "y", "decimal", constraints=[{"kind": "range", "expression": "minimum=0"}, {"kind": "range", "expression": "maximum=10"}]
        ).constraints
        score = pattern_range_similarity(a or [], b or [])
        assert score == 0.0

    def test_length_kind_overlap(self) -> None:
        a = _attr(
            "x", "string", constraints=[{"kind": "length", "expression": "minLength=1"}, {"kind": "length", "expression": "maxLength=10"}]
        ).constraints
        b = _attr(
            "y", "string", constraints=[{"kind": "length", "expression": "minLength=1"}, {"kind": "length", "expression": "maxLength=10"}]
        ).constraints
        assert pattern_range_similarity(a or [], b or []) == 1.0

    def test_unmatched_kind_is_skipped_when_computing_bounds(self) -> None:
        # A pattern constraint alongside the range constraint - the
        # pattern-kind entry must be skipped when scanning for range
        # bounds, not confused with one.
        a = _attr(
            "x", "integer",
            constraints=[{"kind": "pattern", "expression": "^[0-9]+$"}, {"kind": "range", "expression": "minimum=0"}],
        ).constraints
        b = _attr("y", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        assert pattern_range_similarity(a or [], b or []) == 1.0

    def test_malformed_range_expression_on_second_side_contributes_no_bound(self) -> None:
        a = _attr("x", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        b = _attr("y", "integer", constraints=[{"kind": "range", "expression": "positive"}]).constraints
        assert pattern_range_similarity(a or [], b or []) == 0.0

    def test_identical_single_point_range_is_one(self) -> None:
        a = _attr(
            "x", "integer", constraints=[{"kind": "range", "expression": "minimum=5"}, {"kind": "range", "expression": "maximum=5"}]
        ).constraints
        assert pattern_range_similarity(a or [], a or []) == 1.0

    def test_malformed_range_expression_contributes_no_bound(self) -> None:
        a = _attr("x", "integer", constraints=[{"kind": "range", "expression": "positive"}]).constraints
        b = _attr("y", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}]).constraints
        # a's range constraint doesn't match minimum=/maximum= at all, so
        # _numeric_bounds finds nothing for a - no comparable bound on
        # either side, no score contributed for this kind, and no other
        # shared kind exists -> 0.0.
        assert pattern_range_similarity(a or [], b or []) == 0.0

    def test_identical_range_is_one(self) -> None:
        a = _attr(
            "x", "integer", constraints=[{"kind": "range", "expression": "minimum=0"}, {"kind": "range", "expression": "maximum=10"}]
        ).constraints
        score = pattern_range_similarity(a or [], a or [])
        assert score == 1.0


class TestConstraintOverlap:
    def test_shared_enumeration_dominates(self) -> None:
        a = _profiled("status", "string", enumeration=[{"value": "OPEN"}, {"value": "CLOSED"}])
        b = _profiled("state", "string", enumeration=[{"value": "OPEN"}, {"value": "PENDING"}])
        assert constraint_overlap(a, b) == 1 / 3

    def test_falls_back_to_pattern_range_when_no_enum(self) -> None:
        a = _profiled("x", "string")
        b = _profiled("y", "string")
        assert constraint_overlap(a, b) == 0.5  # neither declares constraints -> neutral


class TestComputeEmbeddings:
    def test_deterministic_and_keyed_by_attribute_id(self) -> None:
        a = _profiled("lossDate", "date")
        embeddings_1 = compute_embeddings([a], dimensions=16)
        embeddings_2 = compute_embeddings([a], dimensions=16)
        assert embeddings_1 == embeddings_2
        assert a.record.attributeId in embeddings_1

    def test_identical_name_no_description_gives_identical_embedding(self) -> None:
        a = _profiled("claimDate", "string", region="uk")
        b = _profiled("claimDate", "string", region="eu")
        embeddings = compute_embeddings([a, b], dimensions=16)
        assert embeddings[a.record.attributeId] == embeddings[b.record.attributeId]


class TestSimilarity:
    def test_identical_attributes_score_high(self) -> None:
        a = _profiled("lossDate", "date")
        b = _profiled("lossDate", "date", attributeId="attr://uk/art-2/Claim.lossDate", region="uk", sourceContract="art-2")
        embeddings = compute_embeddings([a, b], dimensions=64)
        score, features = similarity(a, b, embeddings=embeddings, config=_CFG)
        assert score > 0.6  # identical name/type/no-constraints; parentPath unset on both -> context is not maxed
        assert set(features) == {"lexical", "embedding", "type", "constraints", "context"}
        assert features["lexical"] == 1.0
        assert features["type"] == 1.0

    def test_unrelated_attributes_score_low(self) -> None:
        a = _profiled("claimantName", "string")
        b = _profiled("policyNumber", "string", attributeId="attr://us/art-1/Claim.policyNumber")
        embeddings = compute_embeddings([a, b], dimensions=64)
        score, _ = similarity(a, b, embeddings=embeddings, config=_CFG)
        assert score < _CFG.review_band_low

    def test_weights_sum_to_one_by_default(self) -> None:
        assert abs(sum(_CFG.weights.values()) - 1.0) < 1e-9
