"""
RFC 9457 problem-details error model - Section 12.5's own eight-row
error table, transcribed as real exception types and a real Pydantic
response model. "Error bodies MUST NOT echo corpus content, because
corpus content may be sensitive" (12.1) is enforced by convention here,
not by scanning: every api/*.py error site builds its `detail` text via
`safe_detail()`, a template + named-safe-field call shape that makes
"what's actually going into this message" auditable at each call site,
rather than interpolating request or corpus data directly.
"""

from __future__ import annotations

from pydantic import BaseModel

_PROBLEM_BASE = "https://canonicalmodel.internal/problems"


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    errors: list[str] | None = None


def safe_detail(template: str, **safe_fields: str | int | float | bool) -> str:
    """Builds an error detail string from a static template and named,
    already-known-safe values (ids, counts, enum values, stage names) -
    never raw corpus content. Prefer this over f-strings/string
    concatenation at every api/*.py error call site."""
    return template.format(**safe_fields)


class ApiError(Exception):
    """Base class for every Section 12.5 error type. `status`/
    `type_slug`/`title` are fixed per-subclass (one class per table row);
    `detail`/`instance`/`errors` are supplied per-instance."""

    status: int
    type_slug: str
    title: str

    def __init__(self, detail: str, *, instance: str | None = None, errors: list[str] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.instance = instance
        self.errors = errors

    def to_problem(self) -> ProblemDetail:
        return ProblemDetail(
            type=f"{_PROBLEM_BASE}/{self.type_slug}",
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=self.instance,
            errors=self.errors,
        )


class InvalidContractError(ApiError):
    status = 400
    type_slug = "invalid-contract"
    title = "Body fails schema validation"


class ToolNotAuthorisedError(ApiError):
    status = 403
    type_slug = "tool-not-authorised"
    title = "An agent requested a tool outside its allow-list"


class CorpusDriftError(ApiError):
    status = 409
    type_slug = "corpus-drift"
    title = "A decision was submitted against a checkpoint whose corpus has changed"


class RunConflictError(ApiError):
    status = 409
    type_slug = "run-conflict"
    title = "An active run already exists for the domain"


class GatesNotSatisfiedError(ApiError):
    status = 422
    type_slug = "gates-not-satisfied"
    title = "Release attempted with failing coverage gates or round-trip tests"


class LicenceBlockedError(ApiError):
    status = 424
    type_slug = "licence-blocked"
    title = "An operation required an artefact whose licence disposition is not permitted"


class BudgetExhaustedError(ApiError):
    status = 429
    type_slug = "budget-exhausted"
    title = "The run or stage token or cost ceiling was reached"


class ProviderUnavailableError(ApiError):
    status = 503
    type_slug = "provider-unavailable"
    title = "Model provider unavailable after retries. Run pauses rather than failing"


class NotFoundError(ApiError):
    """Not one of Section 12.5's own eight rows - a plain 404 for a
    run/checkpoint/release/workshop/artefact id that simply doesn't
    exist, needed by nearly every GET endpoint and never named because
    the spec's own error table only enumerates the *unusual* cases."""

    status = 404
    type_slug = "not-found"
    title = "The requested resource does not exist"
