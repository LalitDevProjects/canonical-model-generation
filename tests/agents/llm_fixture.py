"""The anthropic_key fixture, deliberately NOT named conftest.py - same
mypy module-name-collision reasoning as tests/substrate/db_fixture.py.
Skips cleanly with an actionable message when ANTHROPIC_API_KEY isn't
set, the same pattern tests/substrate/db_fixture.py's substrate_db
fixture uses for an unreachable Postgres."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture
def anthropic_key() -> Iterator[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set - see README for how to get an Anthropic API key")
    yield key
