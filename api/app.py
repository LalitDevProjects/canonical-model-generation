"""
Section 12's Internal service APIs - the FastAPI application factory.
Wires the three routers (run-control, registry, workshop) against real,
shared stores/settings built once here, registers the RFC 9457 exception
handler for every api.errors.ApiError subclass, and applies the
bearer-token dependency (api/auth.py) to every route.

`create_app()`'s own defaults are what `uvicorn api.app:create_app
--factory` calls with no arguments - real stores rooted at the repo root,
real settings from config/platform.yaml, real bearer-token enforcement.
Tests pass `base_path=tmp_path, require_auth=False` to isolate storage
and skip re-attaching an Authorization header to every request; a
dedicated auth test exercises `require_auth=True` for real.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from agents.model_gateway import ModelGateway, anthropic_provider
from config.settings import PlatformSettings, load_settings
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from pipeline.registry_store import RegistryStore
from pipeline.run_store import RunStore
from pipeline.workshop_store import WorkshopStore

from api.auth import make_bearer_token_dependency
from api.errors import ApiError
from api.idempotency import IdempotencyStore
from api.registry import build_registry_router
from api.run_control import build_run_control_router
from api.workshop import build_workshop_router


def _model_gateway_factory(settings: PlatformSettings) -> Callable[[], ModelGateway | None]:
    """Checked lazily, per call - not once at app startup - so a test or
    a real deployment can flip ANTHROPIC_API_KEY in the environment
    between requests without restarting the server."""

    def factory() -> ModelGateway | None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        return ModelGateway(tier_config=settings.models.tiers, provider=anthropic_provider())

    return factory


def create_app(
    *,
    settings: PlatformSettings | None = None,
    base_path: Path | None = None,
    require_auth: bool = True,
) -> FastAPI:
    settings = settings or load_settings()

    def _store_path(name: str) -> Path | None:
        return (base_path / name) if base_path is not None else None

    run_store = RunStore(base_path=_store_path("run-store"))
    evidence_store = EvidenceStore(base_path=_store_path("evidence-store"))
    ledger_store = LedgerStore(base_path=_store_path("ledger-store"))
    registry_store = RegistryStore(base_path=_store_path("registry-store"))
    workshop_store = WorkshopStore(base_path=_store_path("workshop-store"))
    idempotency = IdempotencyStore()

    app = FastAPI(title="Canonical Model Generation Platform - Internal Service APIs", version="v1")

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        problem = exc.to_problem()
        return JSONResponse(
            status_code=problem.status,
            content=problem.model_dump(exclude_none=True),
            media_type="application/problem+json",
        )

    dependencies: list[Any] = [Depends(make_bearer_token_dependency(settings))] if require_auth else []

    app.include_router(
        build_run_control_router(
            run_store=run_store,
            settings=settings,
            evidence_store=evidence_store,
            ledger_store=ledger_store,
            model_gateway_factory=_model_gateway_factory(settings),
            idempotency=idempotency,
        ),
        dependencies=dependencies,
    )
    app.include_router(
        build_registry_router(registry_store=registry_store, run_store=run_store, settings=settings),
        dependencies=dependencies,
    )
    app.include_router(
        build_workshop_router(workshop_store=workshop_store, run_store=run_store, settings=settings),
        dependencies=dependencies,
    )

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
