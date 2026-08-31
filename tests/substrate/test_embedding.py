from __future__ import annotations

import math

import pytest

from substrate.embedding import mock_embed, vector_literal


class TestMockEmbed:
    def test_deterministic_for_the_same_text(self) -> None:
        assert mock_embed("claimId", dimensions=16) == mock_embed("claimId", dimensions=16)

    def test_different_text_produces_a_different_vector(self) -> None:
        assert mock_embed("claimId", dimensions=16) != mock_embed("lossDate", dimensions=16)

    def test_produces_exactly_the_requested_dimension(self) -> None:
        assert len(mock_embed("claimId", dimensions=1024)) == 1024
        assert len(mock_embed("claimId", dimensions=1)) == 1
        assert len(mock_embed("claimId", dimensions=8)) == 8

    def test_result_is_l2_normalised(self) -> None:
        vector = mock_embed("claimId", dimensions=64)
        norm = math.sqrt(sum(v * v for v in vector))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_case_and_whitespace_insensitive_normalisation(self) -> None:
        assert mock_embed("Claim  Id", dimensions=16) == mock_embed("claim id", dimensions=16)

    def test_rejects_non_positive_dimensions(self) -> None:
        with pytest.raises(ValueError):
            mock_embed("claimId", dimensions=0)
        with pytest.raises(ValueError):
            mock_embed("claimId", dimensions=-1)

    def test_values_are_within_the_unit_range(self) -> None:
        vector = mock_embed("a rather long description of a claim attribute", dimensions=32)
        assert all(-1.0 <= v <= 1.0 for v in vector)


class TestVectorLiteral:
    def test_formats_as_a_pgvector_bracketed_list(self) -> None:
        assert vector_literal([0.5, -0.25, 1.0]) == "[0.50000000,-0.25000000,1.00000000]"

    def test_empty_list_formats_as_empty_brackets(self) -> None:
        assert vector_literal([]) == "[]"
