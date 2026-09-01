"""
Section 12.3's Registry API. A thin HTTP layer over pipeline.registry_store
and emit.release for GET .../releases[/{semver}[/artefacts/{path}]] and
POST .../releases; GET .../diff is the one genuinely new piece of logic
anywhere in this API layer - nothing existing computes a release diff.

`breaking` is a documented heuristic, not a real semantic-versioning
analysis: a changed or removed artefact under a core (non-extension)
path counts as breaking. `causeAttribution` is an honestly-labelled
structural stub - {evidence: 0, prompt: 0, model: 0} always - because no
module anywhere in this repo computes real evidence/prompt/model
provenance for a diff; inventing a heuristic that *looked* meaningful
here would misrepresent what this endpoint can actually attribute.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Response

from algorithms.coverage import coverage
from config.settings import PlatformSettings
from emit.release import build_release_manifest, validate_release_manifest
from pipeline.registry_store import RegistryStore
from pipeline.run_store import RunStore

from api.coverage_support import live_universe
from api.errors import GatesNotSatisfiedError, NotFoundError, safe_detail
from api.schemas import CreateReleaseRequest, DiffCauseAttribution, ReleaseDiffResponse, ReleaseSummary


def _extension_path(path: str) -> bool:
    return path.startswith("extensions/")


def build_registry_router(*, registry_store: RegistryStore, run_store: RunStore, settings: PlatformSettings) -> APIRouter:
    router = APIRouter(prefix="/v1/registry", tags=["registry"])

    @router.get("/{domain}/releases", response_model=list[ReleaseSummary])
    def list_releases(domain: str) -> list[ReleaseSummary]:
        return [
            ReleaseSummary(semver=r.version, signedAt=r.signed_at, coverage=r.coverage, conformance=r.conformance)
            for r in registry_store.list_releases(domain)
        ]

    @router.get("/{domain}/releases/{semver}")
    def get_release(domain: str, semver: str) -> dict[str, object]:
        try:
            manifest = registry_store.read_release(domain, semver)
        except FileNotFoundError as exc:
            raise NotFoundError(safe_detail("release {domain}/{semver} not found", domain=domain, semver=semver)) from exc
        return manifest.to_dict()

    @router.get("/{domain}/releases/{semver}/artefacts/{path:path}")
    def get_artefact(domain: str, semver: str, path: str) -> Response:
        try:
            content, media_type = registry_store.read_artefact(domain, semver, path)
        except FileNotFoundError as exc:
            raise NotFoundError(
                safe_detail("artefact {path} not found in release {domain}/{semver}", path=path, domain=domain, semver=semver)
            ) from exc
        return Response(content=content, media_type=media_type)

    @router.post("/{domain}/releases", status_code=201)
    def create_release(domain: str, body: CreateReleaseRequest) -> dict[str, object]:
        run_id = UUID(body.runId)
        universe = live_universe(run_store, run_id, settings)
        if universe is None:
            raise GatesNotSatisfiedError(safe_detail("run {run_id} has no computable coverage yet", run_id=body.runId))

        report = coverage(universe, domain, config=settings.coverage)
        if not (report.gate1Pass and report.gate2Pass and report.gate3Pass):
            raise GatesNotSatisfiedError(
                safe_detail("coverage gates not satisfied for run {run_id} (score {score})", run_id=body.runId, score=report.score)
            )

        run_manifest = run_store.read_run_manifest(run_id)
        release_manifest = build_release_manifest(
            domain=domain,
            version=body.semver,
            run_id=body.runId,
            corpus_hash=run_manifest.corpusHash,
            pins=run_manifest.pins.model_dump(),
            # No emitted artefact set is attached to a run by this API
            # layer - emit.workshop_pack.assemble_pack is a separate,
            # manually-invoked path (see docs/increments.md's own
            # "still out of scope" note); a release created here carries
            # its coverage/gate outcome for real, with an empty artefact
            # list until that pack is wired in as a follow-on.
            artefacts=[],
            coverage_score=report.score,
            gate1=report.gate1Pass,
            gate2=report.gate2Pass,
            gate3=report.gate3Pass,
            acord_conformance=0.0,
            decisions=body.decisions,
            approvers=[a.model_dump() for a in body.approvers],
            signature="unsigned-poc-placeholder",
        )
        payload = release_manifest.to_dict()
        validate_release_manifest(payload)
        registry_store.write_release(domain, release_manifest)
        return payload

    @router.get("/{domain}/diff", response_model=ReleaseDiffResponse)
    def diff_releases(domain: str, from_: str = Query(alias="from"), to: str = Query()) -> ReleaseDiffResponse:
        try:
            from_manifest = registry_store.read_release(domain, from_)
            to_manifest = registry_store.read_release(domain, to)
        except FileNotFoundError as exc:
            raise NotFoundError(
                safe_detail("one or both releases not found for domain {domain}: {from_}, {to}", domain=domain, from_=from_, to=to)
            ) from exc

        from_by_path = {a.path: a.sha256 for a in from_manifest.artefacts}
        to_by_path = {a.path: a.sha256 for a in to_manifest.artefacts}

        added = sorted(set(to_by_path) - set(from_by_path))
        removed = sorted(set(from_by_path) - set(to_by_path))
        changed = sorted(p for p in (set(from_by_path) & set(to_by_path)) if from_by_path[p] != to_by_path[p])
        breaking = any(not _extension_path(p) for p in [*changed, *removed])

        return ReleaseDiffResponse(
            added=added, changed=changed, removed=removed, breaking=breaking,
            causeAttribution=DiffCauseAttribution(evidence=0, prompt=0, model=0),
        )

    return router
