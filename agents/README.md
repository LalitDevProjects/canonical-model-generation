# agents

Populated at Increment 6. The `Agent` base contract (Section 7.1) and
two real agents proving it end to end.

- `base.py` - `Agent(ABC)`'s literal ten-step `invoke()` path,
  `WorkItem`/`RunContext`/`AgentResult`. `route()` is an identity stub -
  no S1-S8 orchestrator exists or is in scope this increment (Section
  8.3's own pseudocode is an AWS Step Functions definition this repo has
  no way to run).
- `deterministic.py` - `DeterministicAgent(Agent)`: `model_tier: n/a`,
  no prompt, no model call, no retry loop (Section 7.6's retry table
  doesn't apply to a pure function - retrying it changes nothing).
- `validation.py` - the V1-V5 validation ladder (Section 7.3), plus the
  `Violation`/`Guardrail` shapes and every ladder-related exception type
  - the lower layer `base.py`/`deterministic.py` build on, specifically
  to avoid a circular import (a `Guardrail`'s own check callback needs a
  `RunContext`, defined in `base.py`). `validate_schema()` gained an
  optional `registry: Registry | None` kwarg at Increment 7 (default
  `None` preserves Increment 6's two agents' exact behaviour) - needed
  to resolve `contracts/C6/ConceptCluster/1.0.json`'s external `$ref`s
  into `common/defs.json` for Semantic Resolver's own output_schema.
- `model_gateway.py` - `Budget` (transcribed from Section 7.6, one real
  bug fixed), `ModelGateway` with a real Anthropic-backed provider
  (`anthropic_provider()`) and an injectable one for tests
  (`ProviderFn`). Structured output is enforced by this repo's own
  `validate_schema`, not assumed provider-side.
- `prompt_render.py` - `render()`, the single prompt-construction site
  (Section 7.4: "String concatenation of model input anywhere in the
  codebase is a review failure"). Loads `prompts/{template_id}/{version}.md`,
  requires all six blocks present.
- `repository_scout.py` - Repository Scout, explicitly deferred to this
  increment back at Increment 2
  (`connectors/relevance.py::default_uncertain_policy`'s own docstring).
  `make_repository_scout_classifier(ctx)` is a factory whose returned
  closure is a drop-in for `filter_relevance`'s own `scout_classifier`
  parameter - zero changes to `connectors/relevance.py`.
- `schema_interpreter.py` - Schema Interpreter, a thin wrapper around
  the already-real `parsers/router.py::parse`, reached through the
  `spec.parse` tool (not called directly), so the same authorisation/
  audit path a model-calling agent's tool use goes through also covers
  this deterministic one.
- `semantic_resolver.py` (Increment 7) - Semantic Resolver (Section
  7.5.1), adjudicating only the review-band material
  `algorithms/clustering.py::run_clustering()` sets aside (the
  deterministic pipeline decides every confidently-linked pair on its
  own) - the same "deterministic decides, agent adjudicates the
  uncertain band" shape Repository Scout already established for
  relevance filtering. `output_schema` is the real, unmodified
  `contracts/C6/ConceptCluster/1.0.json` (loaded from disk, not
  hand-copied), with a `schema_registry` built once at import time.
  Five real, code-checkable guardrails (G1-G5, transcribed verbatim
  from the spec). `make_semantic_resolver_adjudicator(ctx)` is a
  factory - the same shape as `make_repository_scout_classifier` -
  grouping review-band pairs into connected components, one `WorkItem`
  per component, persisting `AWAIT_TRIAGE` escalations to the same
  triage sink the deterministic pipeline uses.

See `docs/increments.md` for what each increment built and verified
(including the real Anthropic API decision and the `tool.denied`
contract gap Increment 6 closed, and Increment 7's empirically-found
clustering-weights fix), and `tools/README.md` for the tool gateway
these agents reach every external capability through.
