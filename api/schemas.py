"""
Pydantic request/response envelope models for Section 12's three API
groups (run-control, registry, workshop). Response bodies reuse
generated/ contract models directly (C11Runmanifest, C9Coveragereport,
C9Gapentry, C11Journalevent) or emit/'s own dataclasses (ReleaseManifest,
WorkshopPackManifest) as FastAPI response_models wherever the spec's own
response literally IS that object - these classes cover only the small
envelope shapes (create responses, listings, the checkpoint/pack views)
the spec names but no existing contract represents.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TriggerRequest(BaseModel):
    kind: str
    requestedBy: str
    at: str


class CreateRunRequest(BaseModel):
    domain: str
    trigger: TriggerRequest
    pins: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    previousRunId: str | None = None


class CreateRunResponse(BaseModel):
    runId: str
    state: str


class RunStateResponse(BaseModel):
    state: str


class JournalPage(BaseModel):
    events: list[dict[str, Any]]
    nextCursor: str | None = None


class CheckpointView(BaseModel):
    checkpoint: str
    sealedAt: str
    payloadRef: str
    items: list[dict[str, Any]]


class DecisionItem(BaseModel):
    itemId: str
    outcome: str
    rationale: str
    decidedBy: str


class SubmitCheckpointDecisionsRequest(BaseModel):
    decisions: list[DecisionItem]
    complete: bool = False


class SubmitDecisionsAccepted(BaseModel):
    accepted: int
    runState: str


class GapPage(BaseModel):
    gaps: list[dict[str, Any]]
    nextCursor: str | None = None


class ApproverItem(BaseModel):
    role: str
    name: str
    at: str


class CreateReleaseRequest(BaseModel):
    runId: str
    semver: str
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    approvers: list[ApproverItem] = Field(default_factory=list)


class ReleaseSummary(BaseModel):
    semver: str
    signedAt: str
    coverage: dict[str, Any]
    conformance: dict[str, Any]


class DiffCauseAttribution(BaseModel):
    evidence: int
    prompt: int
    model: int


class ReleaseDiffResponse(BaseModel):
    added: list[str]
    changed: list[str]
    removed: list[str]
    breaking: bool
    causeAttribution: DiffCauseAttribution


class WorkshopParticipant(BaseModel):
    name: str
    region: str
    role: str


class CreateWorkshopRequest(BaseModel):
    runId: str
    domain: str
    checkpoint: str
    participants: list[WorkshopParticipant] = Field(default_factory=list)


class CreateWorkshopResponse(BaseModel):
    workshopId: str
    packRef: str


class WorkshopPackView(BaseModel):
    conflicts: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    weights: list[dict[str, Any]]
    declaredLosses: list[dict[str, Any]]
    openQuestions: list[dict[str, Any]]
    coveragePreview: dict[str, Any]


class WorkshopDecisionItem(BaseModel):
    candidateId: str
    outcome: str
    amendment: str | None = None
    weight: int | None = None
    rationale: str
    sme: str


class SubmitWorkshopDecisionsRequest(BaseModel):
    decisions: list[WorkshopDecisionItem]


class WorkshopDecisionsRecorded(BaseModel):
    recorded: int
