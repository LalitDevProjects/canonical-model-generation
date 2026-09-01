"""
Real-model test for pipeline/orchestrator.py::resume_after_checkpoint's
TRIAGE continuation - a genuine Anthropic API call through the real
`anthropic_provider()` (agents/model_gateway.py), not a scripted fake.
Skips cleanly without ANTHROPIC_API_KEY (see llm_fixture.py), matching
every other pytest.mark.llm test in this repo.

tests/pipeline/test_orchestrator.py's own TestResumeAfterCheckpointFullContinuation
already proves the continuation's wiring hermetically with a scripted
provider; this test is the supplementary "does it really work against
the real model" check the rest of this repo already reserves
pytest.mark.llm for (agents/test_anthropic_provider.py, etc.) - not the
primary source of coverage for this code path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orchestrator_llm_fixture import anthropic_key

from agents.model_gateway import ModelGateway, anthropic_provider
from config.settings import ModelProvider, ModelTierConfig, load_settings
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from pipeline.orchestrator import create_run, resume_after_checkpoint
from pipeline.run_store import RunStore

pytestmark = pytest.mark.llm


def test_real_model_continuation_produces_at_least_one_real_candidate(tmp_path: Path, anthropic_key: str) -> None:
    run_store = RunStore(base_path=tmp_path / "run-store")
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    ledger_store = LedgerStore(base_path=tmp_path / "ledger-store")
    settings = load_settings()

    manifest = create_run(
        domain="claims",
        trigger={"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
        pins=None, parameters=None, budget=None, previous_run_id=None,
        settings=settings, run_store=run_store, evidence_store=evidence_store, ledger_store=ledger_store,
    )
    run_store.write_checkpoint_decisions(manifest.runId, "TRIAGE", [{"itemId": "x"}], complete=True)

    tier_config = {
        "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")
    }
    gateway = ModelGateway(tier_config=tier_config, provider=anthropic_provider(anthropic_key))

    result = resume_after_checkpoint(
        run_id=manifest.runId, checkpoint="TRIAGE", run_store=run_store, settings=settings, model_gateway=gateway,
    )

    assert result.state == "CANDIDATES_READY"
    candidates = run_store.read_candidates(manifest.runId)
    assert candidates, "expected at least one real candidate from a real model call"
