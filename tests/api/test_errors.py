"""
Hermetic tests for Section 12.5's error model, over real HTTP responses.
Covers every row of that table this API layer's own real routes can
actually reach: 400, 404 (not one of the 8 rows - see api/errors.py's
own NotFoundError docstring), 409 (both variants), 422, 429, 503.

403 tool-not-authorised and 424 licence-blocked are mapped in
api/run_control.py's own exception handling (ToolDenied ->
ToolNotAuthorisedError is real code, not dead), but neither this
increment's own routes nor the hermetic TRIAGE continuation ever
constructs a scenario that reaches them - ToolDenied only fires for a
tool call outside an agent's own static allow-list, which none of the
three agents this continuation invokes (ACORD Aligner, Canonical
Synthesiser) ever attempts, and LicenceBlockedError has no call site
anywhere in this API layer at all (ACORD Aligner always degrades before
reaching a tool call, per Section 19.2). Documented here rather than
faked with a contrived, unrealistic trigger.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agents.model_gateway import ModelGateway, ModelProviderError, ProviderResponse
from config.settings import ModelProvider, ModelTierConfig, load_settings
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from pipeline.run_store import RunStore

from api.errors import ApiError
from api.idempotency import IdempotencyStore
from api.run_control import build_run_control_router

pytestmark = pytest.mark.e2e


def _failing_provider(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
    raise ModelProviderError("simulated provider outage")


def _app_with_gateway_factory(tmp_path: Path, gateway: ModelGateway | None) -> TestClient:
    """Bypasses api.app.create_app() (which always resolves the model
    gateway from ANTHROPIC_API_KEY) to inject a specific, scripted
    ModelGateway directly into the run-control router - the same
    factory-injection seam the router itself is built around."""
    settings = load_settings()
    run_store = RunStore(base_path=tmp_path / "run-store")
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    ledger_store = LedgerStore(base_path=tmp_path / "ledger-store")

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        problem = exc.to_problem()
        return JSONResponse(status_code=problem.status, content=problem.model_dump(exclude_none=True))

    app.include_router(
        build_run_control_router(
            run_store=run_store, settings=settings, evidence_store=evidence_store, ledger_store=ledger_store,
            model_gateway_factory=lambda: gateway, idempotency=IdempotencyStore(),
        )
    )
    return TestClient(app)


def _create_run(client: TestClient, *, budget: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "domain": "claims", "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"}
    }
    if budget is not None:
        payload["budget"] = budget
    response = client.post("/v1/runs", json=payload)
    assert response.status_code == 201, response.text
    run_id: str = response.json()["runId"]
    return run_id


class TestInvalidContract400:
    def test_unsupported_domain(self, tmp_path: Path) -> None:
        client = _app_with_gateway_factory(tmp_path, None)
        response = client.post(
            "/v1/runs",
            json={"domain": "policy", "trigger": {"kind": "manual", "requestedBy": "t", "at": "2026-08-31T12:00:00Z"}},
        )
        assert response.status_code == 400
        assert response.json()["type"].endswith("/invalid-contract")


class TestNotFound404:
    def test_unknown_run(self, tmp_path: Path) -> None:
        client = _app_with_gateway_factory(tmp_path, None)
        response = client.get("/v1/runs/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert response.json()["type"].endswith("/not-found")


class TestCorpusDrift409:
    def test_decisions_against_a_drifted_corpus(self, tmp_path: Path) -> None:
        from uuid import UUID

        client = _app_with_gateway_factory(tmp_path, None)
        run_id = _create_run(client)
        store = RunStore(base_path=tmp_path / "run-store")
        drifted = store.read_run_manifest(UUID(run_id)).model_copy(update={"corpusHash": "f" * 64})
        store.write_run_manifest(UUID(run_id), drifted)

        response = client.post(
            f"/v1/runs/{run_id}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/corpus-drift")


class TestRunConflict409:
    def test_second_active_run_for_the_same_domain(self, tmp_path: Path) -> None:
        client = _app_with_gateway_factory(tmp_path, None)
        _create_run(client)
        response = client.post(
            "/v1/runs",
            json={"domain": "claims", "trigger": {"kind": "manual", "requestedBy": "t", "at": "2026-08-31T12:00:00Z"}},
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/run-conflict")


class TestProviderUnavailable503:
    def test_a_failing_provider_surfaces_as_503(self, tmp_path: Path) -> None:
        tier_config = {
            "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")
        }
        gateway = ModelGateway(
            tier_config=tier_config, provider=_failing_provider, max_provider_retries=0, sleep_fn=lambda _: None
        )
        client = _app_with_gateway_factory(tmp_path, gateway)
        run_id = _create_run(client)

        response = client.post(
            f"/v1/runs/{run_id}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 503
        assert response.json()["type"].endswith("/provider-unavailable")


class TestBudgetExhausted429:
    def test_a_zero_token_run_budget_surfaces_as_429(self, tmp_path: Path) -> None:
        # The run's own real, persisted budget (RunManifest.budget, from
        # the POST /v1/runs request body) is what pipeline/orchestrator.py::
        # _build_run_context() now builds GatewayBudget.from_contract()
        # against - a tokensTotal=0 ceiling guarantees Budget.check()
        # trips BudgetExceeded before any provider call, regardless of
        # prompt size.
        tier_config = {
            "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=16000, model_id="claude-sonnet-5")
        }

        def _unused_provider(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
            raise AssertionError("provider must not be called once the budget is already exhausted")

        gateway = ModelGateway(tier_config=tier_config, provider=_unused_provider)
        client = _app_with_gateway_factory(tmp_path, gateway)
        run_id = _create_run(client, budget={"tokensTotal": 0, "costCeilingGbp": 100.0, "perStage": {}})

        response = client.post(
            f"/v1/runs/{run_id}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 429
        assert response.json()["type"].endswith("/budget-exhausted")
