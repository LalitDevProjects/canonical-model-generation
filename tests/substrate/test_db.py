from __future__ import annotations

import pytest

from substrate.db import SubstrateDb

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly

pytestmark = pytest.mark.db


class TestSearchPathSql:
    """A pure string-composition check, no live connection needed - kept
    separate from the pytest.mark.db tests below since it doesn't touch
    the shared "public" schema at all."""

    def test_public_schema_has_no_redundant_second_entry(self) -> None:
        db = SubstrateDb("postgresql://unused/unused", schema="public")
        assert db._search_path_sql().as_string(None) == 'SET search_path TO "public"'

    def test_non_public_schema_keeps_public_reachable_too(self) -> None:
        db = SubstrateDb("postgresql://unused/unused", schema="my_schema")
        assert db._search_path_sql().as_string(None) == 'SET search_path TO "my_schema", public'


class TestEnsureSchema:
    def test_creates_the_expected_tables(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() ORDER BY table_name"
            ).fetchall()
        table_names = {row[0] for row in rows}
        assert table_names == {"attribute_embeddings", "chunks", "edges", "nodes"}

    def test_is_idempotent(self, substrate_db: SubstrateDb) -> None:
        substrate_db.ensure_schema(dimensions=8)
        substrate_db.ensure_schema(dimensions=8)

    def test_pgvector_extension_is_available(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            row = conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()
        assert row is not None


class TestConnection:
    def test_search_path_is_scoped_to_the_given_schema(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            row = conn.execute("SHOW search_path").fetchone()
        assert row is not None
        assert substrate_db._schema in row[0]

    def test_writes_are_visible_after_the_context_manager_commits(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            conn.execute(
                "INSERT INTO nodes (node_id, node_type, properties) VALUES (%s, %s, %s)",
                ("art-1", "Artefact", "{}"),
            )
        with substrate_db.connection() as conn:
            row = conn.execute("SELECT node_id FROM nodes WHERE node_id = %s", ("art-1",)).fetchone()
        assert row is not None

    def test_rolls_back_on_exception(self, substrate_db: SubstrateDb) -> None:
        with pytest.raises(RuntimeError):
            with substrate_db.connection() as conn:
                conn.execute(
                    "INSERT INTO nodes (node_id, node_type, properties) VALUES (%s, %s, %s)",
                    ("art-2", "Artefact", "{}"),
                )
                raise RuntimeError("boom")
        with substrate_db.connection() as conn:
            row = conn.execute("SELECT node_id FROM nodes WHERE node_id = %s", ("art-2",)).fetchone()
        assert row is None
