"""The substrate_db fixture, deliberately NOT named conftest.py: pytest
requires that literal filename for directory-scoped auto-discovery, but
mypy (run over the whole tests/ tree in one pass, no __init__.py markers
anywhere under tests/) resolves a bare module name per file and cannot
tell two differently-located conftest.py files apart - the same
"Duplicate module named conftest" collision Increment 3 hit between
tests/connectors/ and tests/parsers/. That one was fixed by renaming the
file with no real fixtures in it (tests/parsers/golden_helpers.py); this
one can't use that fix since BOTH tests/connectors/conftest.py and this
fixture are genuine, needed conftest content. Each DB-marked test module
in this directory imports substrate_db from here explicitly instead of
relying on conftest.py's automatic directory-wide discovery."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from config.settings import load_settings
from substrate.db import SubstrateDb

TEST_DIMENSIONS = 8
"""Small on purpose: pgvector requires a fixed dimension at CREATE TABLE
time, and the real value (config.models.embedding_dimensions, 1024 in
production) is irrelevant to what these tests actually check - a small
dimension keeps schema creation and vector math fast."""


def _resolve_dsn() -> str:
    """CMGP_STORAGE__POSTGRES_DSN (this repo's own env-var naming
    convention - config/settings.py's PlatformSettings uses the same
    CMGP_ prefix / "__" nested delimiter) overrides
    config/platform.yaml's committed default. load_settings() itself
    does NOT apply this override (it passes every YAML field as an
    explicit constructor kwarg, which pydantic-settings treats as
    higher-precedence than env vars) - reading the env var directly here
    is what lets one developer's machine-local port remap
    (infra/docker-compose.yml, currently 5433 on this machine to avoid a
    pre-existing native Postgres install on 5432) differ from the
    committed default without touching committed config."""
    return os.environ.get("CMGP_STORAGE__POSTGRES_DSN") or load_settings().storage.postgres_dsn


@pytest.fixture
def substrate_db() -> Iterator[SubstrateDb]:
    dsn = _resolve_dsn()
    try:
        probe = psycopg.connect(dsn, connect_timeout=2)
        probe.close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres unreachable at {dsn!r} ({exc}) - run `docker compose -f infra/docker-compose.yml up -d`")

    schema = f"test_{uuid4().hex[:12]}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    db = SubstrateDb(dsn, schema=schema)
    db.ensure_schema(dimensions=TEST_DIMENSIONS)
    try:
        yield db
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")
