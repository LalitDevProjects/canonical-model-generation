"""
Postgres + pgvector connection handling for the knowledge substrate
(Section 6). Mirrors pipeline/run_store.py's RunStore /
gate/ledger.py's LedgerStore / gate/evidence_store.py's EvidenceStore
constructor pattern (a thin wrapper around wherever the real store lives,
overridable in tests) - except a DSN has no repo-relative "sensible
default" the way a filesystem path does, so `dsn` is a required
parameter here rather than defaulting to config.storage.postgres_dsn
internally; callers (production ingestion code, tests) pass whatever DSN
is appropriate, the same explicit-dependency style gate/gate.py's
classify_and_redact already uses for its own keys/config values.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import psycopg
from psycopg import sql

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


class SubstrateDb:
    """schema defaults to "public" (production); tests pass a uniquely
    named schema per test run so parallel/repeated local runs never
    collide - same isolation discipline as connectors/manifest.py's
    corpusHash-stability tests use fresh tmp_path directories."""

    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        self._dsn = dsn
        self._schema = schema

    def _search_path_sql(self) -> sql.Composed:
        """Always keeps "public" reachable alongside the target schema:
        extensions (pgvector's own `vector` type included) are
        conventionally installed once per database into "public", and a
        bare `SET search_path TO {schema}` would otherwise hide that
        type from a non-public test schema entirely."""
        if self._schema == "public":
            return sql.SQL("SET search_path TO {}").format(sql.Identifier("public"))
        return sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self._schema))

    @contextlib.contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Commits on clean exit, rolls back on exception, always closes -
        psycopg3's own Connection context-manager protocol, not
        hand-rolled here."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(self._search_path_sql())
            yield conn

    def ensure_schema(self, *, dimensions: int) -> None:
        """Idempotent: CREATE TABLE IF NOT EXISTS throughout schema.sql,
        safe to call at the start of every run. The schema itself (not
        just its tables) must exist before `search_path` can resolve
        anything in it, so this uses its own connection rather than
        connection() - the chicken-and-egg the ordinary path avoids by
        assuming the schema already exists."""
        template = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
        # str.replace(), not str.format(): schema.sql's own JSONB
        # defaults ('{}'::jsonb) contain literal braces that str.format
        # would misinterpret as positional placeholders.
        ddl = template.replace("{dimensions}", str(dimensions))
        with psycopg.connect(self._dsn) as conn:
            if self._schema != "public":
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self._schema)))
            conn.execute(self._search_path_sql())
            conn.execute(ddl)
