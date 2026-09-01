"""
Section 12.2's Run control API. A thin HTTP layer over pipeline.run_store
and pipeline.orchestrator - every route calls a real, already-tested
function; no business logic is reimplemented here. `build_run_control_router`
is a factory (the same explicit-dependency-injection shape
agents/canonical_synthesiser.py::make_canonical_synthesiser_factory and
api/auth.py::make_bearer_token_dependency already use), not a module-level
singleton, so tests can build a router against a tmp_path-rooted RunStore.

GET .../coverage and GET .../gaps are computed live, on every request,
from whatever clusters/candidates are currently persisted for the run -
cheap and deterministic, matching the design already recorded in the
approved plan (coverage is real and computable as soon as S4 has run,
even with zero candidates yet; a run that hasn't reached S4 gets a 404).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Header, Query

from generated.C11.RunManifest._1_0 import C11Runmanifest

from agents.model_gateway import BudgetExceeded, ModelGateway, ModelProviderError
from algorithms.coverage import coverage, gap_register
from config.settings import PlatformSettings
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from pipeline.orchestrator import (
    CheckpointNotCompleteError,
    CheckpointNotSealedError,
    CorpusDriftDetected,
    UnsupportedDomainError,
    create_run,
    resume_after_checkpoint,
)
from pipeline.run_store import RunStore
from tools.gateway import ToolDenied

from api.coverage_support import live_universe
from api.errors import (
    BudgetExhaustedError,
    CorpusDriftError,
    InvalidContractError,
    NotFoundError,
    ProviderUnavailableError,
    RunConflictError,
    ToolNotAuthorisedError,
    safe_detail,
)
from api.idempotency import IdempotencyStore
from api.pagination import decode_cursor, encode_cursor
from api.schemas import (
    CheckpointView,
    CreateRunRequest,
    CreateRunResponse,
    GapPage,
    JournalPage,
    RunStateResponse,
    SubmitCheckpointDecisionsRequest,
    SubmitDecisionsAccepted,
)

_ACTIVE_STATES = {"CREATED", "RUNNING", "AWAIT_TRIAGE", "AWAIT_MODEL_PROVIDER"}


def _get_run_or_404(run_store: RunStore, run_id: UUID) -> C11Runmanifest:
    try:
        return run_store.read_run_manifest(run_id)
    except FileNotFoundError as exc:
        raise NotFoundError(safe_detail("run {run_id} not found", run_id=str(run_id))) from exc


def build_run_control_router(
    *,
    run_store: RunStore,
    settings: PlatformSettings,
    evidence_store: EvidenceStore,
    ledger_store: LedgerStore,
    model_gateway_factory: Callable[[], ModelGateway | None],
    idempotency: IdempotencyStore,
) -> APIRouter:
    router = APIRouter(prefix="/v1/runs", tags=["run-control"])
    run_locks: dict[UUID, threading.Lock] = defaultdict(threading.Lock)

    @router.post("", response_model=CreateRunResponse, status_code=201)
    def create_run_route(
        body: CreateRunRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
    ) -> CreateRunResponse:
        cached = idempotency.get("POST /v1/runs", idempotency_key)
        if cached is not None:
            assert isinstance(cached, CreateRunResponse)
            return cached

        active = [m for m in run_store.list_runs(domain=body.domain) if m.state in _ACTIVE_STATES]
        if active:
            raise RunConflictError(safe_detail("an active run already exists for domain {domain}", domain=body.domain))

        try:
            manifest = create_run(
                domain=body.domain,
                trigger=body.trigger.model_dump(),
                pins=body.pins,
                parameters=body.parameters,
                budget=body.budget,
                previous_run_id=UUID(body.previousRunId) if body.previousRunId else None,
                settings=settings,
                run_store=run_store,
                evidence_store=evidence_store,
                ledger_store=ledger_store,
            )
        except UnsupportedDomainError as exc:
            raise InvalidContractError(safe_detail("{detail}", detail=str(exc))) from exc

        response = CreateRunResponse(runId=str(manifest.runId), state=manifest.state)
        idempotency.put("POST /v1/runs", idempotency_key, response)
        return response

    @router.get("/{run_id}", response_model=C11Runmanifest)
    def get_run(run_id: UUID) -> C11Runmanifest:
        return _get_run_or_404(run_store, run_id)

    @router.get("/{run_id}/journal", response_model=JournalPage)
    def get_journal(run_id: UUID, fromSeq: int = Query(default=0), limit: int | None = Query(default=None)) -> JournalPage:
        _get_run_or_404(run_store, run_id)
        events = run_store.read_journal_events(run_id, from_seq=fromSeq, limit=limit)
        # fromSeq is a literal integer per Section 12.2's own worked
        # query-param name, not an opaque cursor - the continuation
        # value is therefore the plain next seq, not a base64 token.
        next_cursor = str(events[-1].seq + 1) if (limit is not None and len(events) == limit) else None
        return JournalPage(events=[e.model_dump(mode="json") for e in events], nextCursor=next_cursor)

    @router.post("/{run_id}/pause", response_model=RunStateResponse, status_code=201)
    def pause_run(run_id: UUID) -> RunStateResponse:
        with run_locks[run_id]:
            _get_run_or_404(run_store, run_id)
            updated = run_store.update_run_state(run_id, "PAUSED")
        return RunStateResponse(state=updated.state)

    @router.post("/{run_id}/resume", response_model=RunStateResponse, status_code=201)
    def resume_run(run_id: UUID) -> RunStateResponse:
        with run_locks[run_id]:
            manifest = _get_run_or_404(run_store, run_id)
            if manifest.state != "PAUSED":
                return RunStateResponse(state=manifest.state)
            updated = run_store.update_run_state(run_id, "RUNNING")
        return RunStateResponse(state=updated.state)

    @router.get("/{run_id}/checkpoints/{checkpoint}", response_model=CheckpointView)
    def get_checkpoint(run_id: UUID, checkpoint: str) -> CheckpointView:
        _get_run_or_404(run_store, run_id)
        sealed = run_store.read_sealed_checkpoint(run_id, checkpoint)
        if sealed is None:
            raise NotFoundError(
                safe_detail("checkpoint {checkpoint} has not been sealed for run {run_id}", checkpoint=checkpoint, run_id=str(run_id))
            )
        items: list[dict[str, object]] = sealed["items"]
        return CheckpointView(
            checkpoint=str(sealed["checkpoint"]), sealedAt=str(sealed["sealedAt"]),
            payloadRef=str(sealed["payloadRef"]), items=items,
        )

    @router.post("/{run_id}/checkpoints/{checkpoint}/decisions", response_model=SubmitDecisionsAccepted, status_code=202)
    def submit_checkpoint_decisions(
        run_id: UUID, checkpoint: str, body: SubmitCheckpointDecisionsRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> SubmitDecisionsAccepted:
        route_key = f"POST /v1/runs/{run_id}/checkpoints/{checkpoint}/decisions"
        cached = idempotency.get(route_key, idempotency_key)
        if cached is not None:
            assert isinstance(cached, SubmitDecisionsAccepted)
            return cached

        with run_locks[run_id]:
            _get_run_or_404(run_store, run_id)
            sealed = run_store.read_sealed_checkpoint(run_id, checkpoint)
            if sealed is None:
                raise NotFoundError(
                    safe_detail("checkpoint {checkpoint} has not been sealed for run {run_id}", checkpoint=checkpoint, run_id=str(run_id))
                )

            current = run_store.read_run_manifest(run_id)
            if current.corpusHash != sealed["corpusHashAtSeal"]:
                raise CorpusDriftError(
                    safe_detail(
                        "run {run_id}'s corpus has changed since checkpoint {checkpoint} was sealed",
                        run_id=str(run_id), checkpoint=checkpoint,
                    )
                )

            run_store.write_checkpoint_decisions(
                run_id, checkpoint, [d.model_dump() for d in body.decisions], complete=body.complete
            )

            run_state = current.state
            if body.complete:
                try:
                    updated = resume_after_checkpoint(
                        run_id=run_id, checkpoint=checkpoint, run_store=run_store,
                        settings=settings, model_gateway=model_gateway_factory(),
                    )
                    run_state = updated.state
                except (CheckpointNotSealedError, CheckpointNotCompleteError):
                    run_state = run_store.read_run_manifest(run_id).state
                except CorpusDriftDetected as exc:
                    raise CorpusDriftError(safe_detail("{detail}", detail=str(exc))) from exc
                except BudgetExceeded as exc:
                    raise BudgetExhaustedError(safe_detail("{detail}", detail=str(exc))) from exc
                except ModelProviderError as exc:
                    raise ProviderUnavailableError(safe_detail("{detail}", detail=str(exc))) from exc
                except ToolDenied as exc:
                    raise ToolNotAuthorisedError(safe_detail("{detail}", detail=str(exc))) from exc

        response = SubmitDecisionsAccepted(accepted=len(body.decisions), runState=run_state)
        idempotency.put(route_key, idempotency_key, response)
        return response

    @router.get("/{run_id}/coverage")
    def get_coverage(run_id: UUID) -> dict[str, object]:
        manifest = _get_run_or_404(run_store, run_id)
        universe = live_universe(run_store, run_id, settings)
        if universe is None:
            raise NotFoundError(safe_detail("run {run_id} has not reached clustering yet", run_id=str(run_id)))
        report = coverage(universe, manifest.domain, config=settings.coverage)
        result: dict[str, object] = report.model_dump(mode="json")
        return result

    @router.get("/{run_id}/gaps", response_model=GapPage)
    def get_gaps(run_id: UUID, cursor: str | None = Query(default=None), limit: int | None = Query(default=None)) -> GapPage:
        manifest = _get_run_or_404(run_store, run_id)
        universe = live_universe(run_store, run_id, settings)
        if universe is None:
            raise NotFoundError(safe_detail("run {run_id} has not reached clustering yet", run_id=str(run_id)))
        report = coverage(universe, manifest.domain, config=settings.coverage)
        gaps = gap_register(universe, report, config=settings.coverage)

        start = decode_cursor(cursor) if cursor is not None else 0
        page = gaps[start : start + limit] if limit is not None else gaps[start:]
        end = start + len(page)
        next_cursor = encode_cursor(end) if end < len(gaps) else None
        return GapPage(gaps=[g.model_dump(mode="json") for g in page], nextCursor=next_cursor)

    return router
