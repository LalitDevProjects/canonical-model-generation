# api

Built as work beyond the 9-increment PoC Build Guide, at the user's
explicit request. Section 12's "Internal service APIs": run-control,
registry, and workshop/decision - a real FastAPI application, not a
placeholder.

- `app.py` - `create_app()`, the application factory. Wires the three
  routers against real, shared stores (`RunStore`, `RegistryStore`,
  `WorkshopStore`, `EvidenceStore`, `LedgerStore`) built once here,
  registers the RFC 9457 exception handler for every `api.errors.ApiError`
  subclass, and applies the bearer-token dependency to every route
  (`require_auth=True` by default; tests pass `False` to skip
  re-attaching an `Authorization` header everywhere). `_model_gateway_factory`
  resolves a real `ModelGateway` lazily, per call, only when
  `ANTHROPIC_API_KEY` is actually set - `None` otherwise, which is what
  keeps a run honestly stuck at `AWAIT_MODEL_PROVIDER` rather than faking
  a continuation.
- `errors.py` - RFC 9457 problem-details (`ProblemDetail`) plus one
  exception class per Section 12.5 table row (`InvalidContractError` 400,
  `ToolNotAuthorisedError` 403, `CorpusDriftError`/`RunConflictError` 409,
  `GatesNotSatisfiedError` 422, `LicenceBlockedError` 424,
  `BudgetExhaustedError` 429, `ProviderUnavailableError` 503) plus
  `NotFoundError` (404 - not one of the spec's own eight rows, needed by
  nearly every `GET`). `safe_detail()` is a template + named-safe-field
  call shape every error site uses, so "error bodies MUST NOT echo corpus
  content" (12.1) is auditable at each call site, not merely asserted.
- `pagination.py` - cursor pagination (12.1: "Cursor pagination on all
  collections. Offset pagination is prohibited"). A plain base64-encoded
  integer - a documented PoC placeholder, not a cryptographically opaque
  token a real deployment would want.
- `idempotency.py` - `IdempotencyStore`, an in-process, non-persistent
  dict keyed by `(route, Idempotency-Key)` - "a repeated key returns the
  original result rather than acting twice" (12.1). Documented as
  PoC-scope; a real deployment needs a distributed store.
- `auth.py` - `make_bearer_token_dependency()`, a structural stand-in for
  12.1's own real "mTLS between components; OAuth 2.0 client credentials
  for human-facing clients" - a single static token
  (`config/settings.py::ApiConfig.bearer_token`), the same
  PoC-placeholder-credential status `EgressConfig.ledger_signing_key`
  already carries.
- `schemas.py` - request bodies and the small envelope response shapes
  (`CreateRunResponse`, `JournalPage`, `CheckpointView`, `ReleaseSummary`,
  `ReleaseDiffResponse`, `WorkshopPackView`, etc.) the spec names but no
  existing contract represents. Responses that literally *are* a
  contract object (`C11Runmanifest`, `C9Coveragereport`, `C9Gapentry`,
  `emit.release.ReleaseManifest`, `emit.workshop_pack.WorkshopPackManifest`)
  are used directly as FastAPI `response_model`s instead.
- `coverage_support.py` - `live_universe()`, shared by `run_control.py`'s
  `GET .../coverage`/`.../gaps` and `registry.py`'s own release gate
  check: computed live, on every request, from whatever clusters/
  candidates are currently persisted for a run - real and deterministic,
  not cached. `None` (a 404) before a run has reached clustering.
- `run_control.py` - Section 12.2, over `pipeline.run_store` and
  `pipeline.orchestrator`. `POST /v1/runs` drives the real, hermetic
  S1->TRIAGE path synchronously within the request; `POST .../checkpoints/
  {checkpoint}/decisions` with `complete: true` calls
  `orchestrator.resume_after_checkpoint()`, mapping its own real
  exceptions (`CorpusDriftDetected`, `agents.model_gateway.BudgetExceeded`/
  `ModelProviderError`, `tools.gateway.ToolDenied`) onto the matching
  Section 12.5 problem-detail type - not just the corpus-drift case the
  spec calls out explicitly.
- `registry.py` - Section 12.3, over `pipeline.registry_store` and
  `emit.release`. `POST .../releases` re-checks coverage gates live
  before signing (422 if unsatisfied); `GET .../diff` is the one
  genuinely new piece of logic anywhere in this package - nothing
  existing computes a release diff. `breaking` is a documented heuristic
  (a changed/removed artefact under a core, non-extension path);
  `causeAttribution` is an honestly-labelled structural stub
  (`{evidence: 0, prompt: 0, model: 0}` always) - no module anywhere in
  this repo computes real evidence/prompt/model provenance for a diff.
- `workshop.py` + `export.py` - Section 12.4, over `pipeline.workshop_store`
  and `emit.workshop_pack.assemble_pack` (the real pack build, not
  reimplemented). `GET .../pack` projects the persisted pack + the run's
  own candidates into the spec's own literal response shape; `conflicts`
  and `openQuestions` are honestly empty (no persisted source exists
  anywhere in this repo for either). `export.py` renders the pack into
  real, readable `.docx`/`.xlsx` documents via `python-docx`/`openpyxl` -
  pure rendering, no new business logic.

New dependencies, all load-bearing: `fastapi`, `uvicorn[standard]`
(actually running the app), `python-docx`, `openpyxl` (the two export
formats 12.4 names). `httpx` (dev-only) backs `fastapi.testclient.TestClient`.

Run it: `uvicorn api.app:create_app --factory --reload` (real stores at
the repo root, real `config/platform.yaml` settings, real bearer-token
enforcement). See root `README.md`'s own "Running the API" section for a
worked request sequence, and `tests/api/` for the full, real, hermetic
test suite (65 tests, ~99% coverage) this package is built against.
