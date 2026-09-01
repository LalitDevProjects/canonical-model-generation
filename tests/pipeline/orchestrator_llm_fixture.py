"""The anthropic_key fixture, deliberately NOT named llm_fixture.py or
conftest.py - both already exist elsewhere under tests/ (tests/agents/
llm_fixture.py, tests/eval/eval_llm_fixture.py), and pytest's rootless
per-directory import mechanism means a duplicate basename anywhere under
tests/ collides for mypy even though pytest itself resolves it fine
per-directory. Named orchestrator_llm_fixture.py to match
tests/eval/eval_llm_fixture.py's own precedent for this exact problem."""

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
