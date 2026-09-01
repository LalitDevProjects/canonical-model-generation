"""
Section 12.4's Workshop and decision API. A thin HTTP layer over
pipeline.workshop_store and emit.workshop_pack.assemble_pack - the real
pack build, not reimplemented.

GET .../pack's own response shape ({conflicts, candidates, weights,
declaredLosses, openQuestions, coveragePreview}) doesn't map cleanly onto
WorkshopPackManifest's own file-index shape (a real directory of files,
not this in-memory preview) - this endpoint projects the persisted pack
data into that literal shape: candidates/weights come from the run's own
persisted CanonicalCandidates, declaredLosses from the pack manifest's
own roll-up, coveragePreview from the pack's own file count. `conflicts`
and `openQuestions` have no persisted source anywhere in this repo (no
conflict-classification output is attached to a workshop record) and are
honestly empty, not fabricated.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response

from algorithms.coverage import coverage, gap_register
from config.settings import PlatformSettings
from emit.release import build_release_manifest
from emit.workshop_pack import assemble_pack
from pipeline.run_store import RunStore
from pipeline.workshop_store import WorkshopStore

from api.coverage_support import live_universe
from api.errors import InvalidContractError, NotFoundError, safe_detail
from api.export import DOCX_MEDIA_TYPE, XLSX_MEDIA_TYPE, render_docx, render_xlsx
from api.schemas import (
    CreateWorkshopRequest,
    CreateWorkshopResponse,
    SubmitWorkshopDecisionsRequest,
    WorkshopDecisionsRecorded,
    WorkshopPackView,
)


def build_workshop_router(*, workshop_store: WorkshopStore, run_store: RunStore, settings: PlatformSettings) -> APIRouter:
    router = APIRouter(prefix="/v1/workshops", tags=["workshop"])

    @router.post("", status_code=201, response_model=CreateWorkshopResponse)
    def create_workshop(body: CreateWorkshopRequest) -> CreateWorkshopResponse:
        run_id = UUID(body.runId)
        try:
            run_manifest = run_store.read_run_manifest(run_id)
        except FileNotFoundError as exc:
            raise NotFoundError(safe_detail("run {run_id} not found", run_id=body.runId)) from exc

        universe = live_universe(run_store, run_id, settings)
        if universe is None:
            raise InvalidContractError(safe_detail("run {run_id} has not reached clustering yet", run_id=body.runId))
        report = coverage(universe, body.domain, config=settings.coverage)
        gaps = gap_register(universe, report, config=settings.coverage)

        release_manifest = build_release_manifest(
            domain=body.domain,
            version="workshop-preview",
            run_id=body.runId,
            corpus_hash=run_manifest.corpusHash,
            pins={},
            artefacts=[],
            coverage_score=report.score,
            gate1=report.gate1Pass,
            gate2=report.gate2Pass,
            gate3=report.gate3Pass,
            acord_conformance=0.0,
            signature="unsigned-workshop-preview",
        )

        workshop_id = uuid4()
        assemble_pack(
            workshop_store.pack_dir(workshop_id),
            domain=body.domain,
            version="workshop-preview",
            candidates=run_store.read_candidates(run_id),
            clusters=run_store.read_clusters(run_id),
            mapping_specs={},
            round_trip_summaries={},
            coverage_report=report,
            gap_register=gaps,
            release_manifest=release_manifest,
        )
        pack_ref = f"/v1/workshops/{workshop_id}/pack"
        workshop_store.write_workshop(workshop_id, {
            "workshopId": str(workshop_id),
            "runId": body.runId,
            "domain": body.domain,
            "checkpoint": body.checkpoint,
            "participants": [p.model_dump() for p in body.participants],
            "packRef": pack_ref,
        })
        return CreateWorkshopResponse(workshopId=str(workshop_id), packRef=pack_ref)

    @router.get("/{workshop_id}/pack", response_model=WorkshopPackView)
    def get_pack(workshop_id: UUID) -> WorkshopPackView:
        try:
            record = workshop_store.read_workshop(workshop_id)
            manifest = workshop_store.read_pack_manifest(workshop_id)
        except FileNotFoundError as exc:
            raise NotFoundError(safe_detail("workshop {workshop_id} not found", workshop_id=str(workshop_id))) from exc

        candidates = run_store.read_candidates(UUID(str(record["runId"])))
        return WorkshopPackView(
            conflicts=[],
            candidates=[c.model_dump(mode="json") for c in candidates],
            weights=[{"candidateId": c.candidateId, "weight": int(c.weight)} for c in candidates],
            declaredLosses=manifest.declared_losses,
            openQuestions=[],
            coveragePreview={"filesInPack": len(manifest.files)},
        )

    @router.post("/{workshop_id}/decisions", response_model=WorkshopDecisionsRecorded, status_code=201)
    def submit_decisions(workshop_id: UUID, body: SubmitWorkshopDecisionsRequest) -> WorkshopDecisionsRecorded:
        try:
            workshop_store.read_workshop(workshop_id)
        except FileNotFoundError as exc:
            raise NotFoundError(safe_detail("workshop {workshop_id} not found", workshop_id=str(workshop_id))) from exc
        workshop_store.append_decisions(workshop_id, [d.model_dump() for d in body.decisions])
        return WorkshopDecisionsRecorded(recorded=len(body.decisions))

    @router.get("/{workshop_id}/export")
    def export_pack(workshop_id: UUID, format: str = Query()) -> Response:
        try:
            manifest = workshop_store.read_pack_manifest(workshop_id)
        except FileNotFoundError as exc:
            raise NotFoundError(safe_detail("workshop {workshop_id} not found", workshop_id=str(workshop_id))) from exc

        if format == "docx":
            return Response(content=render_docx(manifest), media_type=DOCX_MEDIA_TYPE)
        if format == "xlsx":
            return Response(content=render_xlsx(manifest), media_type=XLSX_MEDIA_TYPE)
        raise InvalidContractError(safe_detail("unsupported export format {format}", format=format))

    return router
