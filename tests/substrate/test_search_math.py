from __future__ import annotations

from substrate.search import ChunkRow, bm25_scores, rank_by_score, reciprocal_rank_fuse


class TestBm25Scores:
    def test_empty_query_scores_nothing(self) -> None:
        chunks = [ChunkRow("h1", "claim id notification")]
        assert bm25_scores("", chunks) == {}

    def test_empty_chunk_set_scores_nothing(self) -> None:
        assert bm25_scores("claim", []) == {}

    def test_chunk_containing_the_query_term_scores_above_zero(self) -> None:
        chunks = [ChunkRow("h1", "claim notification date")]
        scores = bm25_scores("claim", chunks)
        assert scores["h1"] > 0

    def test_chunk_never_mentioning_the_query_term_is_absent(self) -> None:
        chunks = [ChunkRow("h1", "claim notification date"), ChunkRow("h2", "policyholder contact phone")]
        scores = bm25_scores("claim", chunks)
        assert "h1" in scores
        assert "h2" not in scores

    def test_more_occurrences_in_a_similarly_sized_document_scores_higher(self) -> None:
        chunks = [
            ChunkRow("h1", "claim claim claim claim claim"),
            ChunkRow("h2", "notification claim notification notification notification"),
            ChunkRow("h3", "notification date"),
        ]
        scores = bm25_scores("notification", chunks)
        # h2 mentions "notification" three times (against a longer
        # document); h3 mentions it once (in a much shorter document).
        # Standard BM25 term-frequency saturation still favours h2 here.
        assert scores["h2"] > scores["h3"]

    def test_case_insensitive(self) -> None:
        chunks = [ChunkRow("h1", "Claim Notification")]
        assert bm25_scores("CLAIM", chunks) == bm25_scores("claim", chunks)

    def test_multi_term_query_sums_contributions(self) -> None:
        chunks = [ChunkRow("h1", "claim notification"), ChunkRow("h2", "claim only")]
        scores = bm25_scores("claim notification", chunks)
        assert scores["h1"] > scores["h2"]


class TestRankByScore:
    def test_sorted_descending_by_score(self) -> None:
        assert rank_by_score({"a": 0.1, "b": 0.9, "c": 0.5}) == ["b", "c", "a"]

    def test_ties_broken_ascending_by_chunk_hash(self) -> None:
        assert rank_by_score({"zzz": 1.0, "aaa": 1.0}) == ["aaa", "zzz"]

    def test_empty_scores_gives_empty_ranking(self) -> None:
        assert rank_by_score({}) == []

    def test_deterministic_across_repeats(self) -> None:
        scores = {"h3": 0.2, "h1": 0.2, "h2": 0.9}
        assert rank_by_score(scores) == rank_by_score(dict(scores))


class TestReciprocalRankFuse:
    def test_a_chunk_ranked_first_by_both_rankers_scores_highest(self) -> None:
        fused = reciprocal_rank_fuse(["h1", "h2", "h3"], ["h1", "h3", "h2"])
        assert rank_by_score(fused)[0] == "h1"

    def test_a_chunk_missing_from_one_ranker_still_contributes_from_the_other(self) -> None:
        fused = reciprocal_rank_fuse(["h1", "h2"], ["h2"])
        assert "h1" in fused
        assert fused["h1"] == 1 / 61  # rank 1 in the first ranker only

    def test_absent_from_every_ranker_is_absent_from_the_result(self) -> None:
        fused = reciprocal_rank_fuse(["h1"], ["h1"])
        assert "h2" not in fused

    def test_deterministic_across_repeats(self) -> None:
        a = reciprocal_rank_fuse(["h1", "h2", "h3"], ["h3", "h1", "h2"])
        b = reciprocal_rank_fuse(["h1", "h2", "h3"], ["h3", "h1", "h2"])
        assert rank_by_score(a) == rank_by_score(b)

    def test_no_rankings_at_all_gives_an_empty_result(self) -> None:
        assert reciprocal_rank_fuse() == {}
