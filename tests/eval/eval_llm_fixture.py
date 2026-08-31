"""The anthropic_key fixture, deliberately NOT named conftest.py or
llm_fixture.py - same mypy module-name-collision reasoning as
tests/substrate/db_fixture.py (llm_fixture.py already exists at
tests/agents/llm_fixture.py, and mypy resolves a bare module name per
file with no __init__.py anywhere under tests/ to disambiguate). A
small, directly-importable duplicate: tests/ has no __init__.py
anywhere, so pytest's bare-import mechanism only makes a module
importable from files in the same directory."""

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
