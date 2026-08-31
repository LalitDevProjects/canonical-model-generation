from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from substrate.db import SubstrateDb
from substrate.embedding import mock_embed, vector_literal
from substrate.search import vector_scores

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly

pytestmark = pytest.mark.db

DIMENSIONS = 8


def _insert_chunk(db: SubstrateDb, *, chunk_hash: str, run_id: UUID, region: str, artefact_kind: str, tier: int, text: str) -> None:
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO chunks
                (chunk_hash, run_id, artefact_id, content_hash, evref, region,
                 artefact_kind, evidence_tier, chunk_text, embedding, embedding_model_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                chunk_hash, run_id, "art-1", "a" * 64, f"evref://uk/git/art-1@{'a' * 16}#x",
                region, artefact_kind, tier, text, vector_literal(mock_embed(text, dimensions=DIMENSIONS)), "mock-v1",
            ),
        )


class TestVectorScores:
    def test_the_identical_text_scores_a_near_perfect_similarity(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h1" + "0" * 62, run_id=run_id, region="uk", artefact_kind="openapi", tier=1, text="claim notification")
        query_embedding = mock_embed("claim notification", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding)
        [(chunk_hash, score)] = scores.items()
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_a_different_run_id_is_never_returned(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        other_run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h2" + "0" * 62, run_id=other_run_id, region="uk", artefact_kind="openapi", tier=1, text="claim notification")
        query_embedding = mock_embed("claim notification", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding)
        assert scores == {}

    def test_region_filter_excludes_other_regions(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h3" + "0" * 62, run_id=run_id, region="us", artefact_kind="openapi", tier=1, text="claim notification")
        query_embedding = mock_embed("claim notification", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding, region="uk")
        assert scores == {}

    def test_artefact_kinds_filter_excludes_other_kinds(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h4" + "0" * 62, run_id=run_id, region="uk", artefact_kind="xsd", tier=1, text="claim notification")
        query_embedding = mock_embed("claim notification", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding, artefact_kinds=["openapi"])
        assert scores == {}

    def test_tier_max_excludes_weaker_evidence(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h5" + "0" * 62, run_id=run_id, region="uk", artefact_kind="openapi", tier=5, text="claim notification")
        query_embedding = mock_embed("claim notification", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding, tier_max=2)
        assert scores == {}

    def test_a_more_similar_chunk_scores_higher_than_a_less_similar_one(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        _insert_chunk(substrate_db, chunk_hash="h6" + "0" * 62, run_id=run_id, region="uk", artefact_kind="openapi", tier=1, text="claim notification date")
        _insert_chunk(substrate_db, chunk_hash="h7" + "0" * 62, run_id=run_id, region="uk", artefact_kind="openapi", tier=1, text="policyholder contact phone")
        query_embedding = mock_embed("claim notification date", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding)
        assert scores["h6" + "0" * 62] > scores["h7" + "0" * 62]

    def test_limit_caps_the_number_of_results(self, substrate_db: SubstrateDb) -> None:
        run_id = uuid4()
        for i in range(5):
            _insert_chunk(substrate_db, chunk_hash=f"h{i}" + "0" * 62, run_id=run_id, region="uk", artefact_kind="openapi", tier=1, text=f"text number {i}")
        query_embedding = mock_embed("text number 0", dimensions=DIMENSIONS)
        with substrate_db.connection() as conn:
            scores = vector_scores(conn, run_id, query_embedding, limit=2)
        assert len(scores) == 2
