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

- `acord_aligner.py` (Increment 8) - ACORD Aligner (Section 7.5.2),
  built in full spec fidelity even though ACORD data has been
  permanently unavailable in this repo since Increment 1 - its own
  guardrail G4 means `align_or_degrade()`'s top-level dispatcher never
  actually invokes it in this repo's own configuration, routing instead
  to Section 19.2's deterministic degraded mode
  (`degraded_alignment()`). G1 (the anti-hallucination control) is
  enforced via `validate_semantics`, not a V4 guardrail - `Guardrail.check`
  has no access to the agent instance, only `validate_semantics` (a
  bound method) does.
- `canonical_synthesiser.py` (Increment 8) - Canonical Synthesiser
  (Section 7.5.3). A genuinely different deterministic/agent
  relationship than Repository Scout/Semantic Resolver's own "the
  algorithm decides confidently, the agent adjudicates the rest" shape:
  here the agent proposes on every item, and `validate_semantics`
  overwrites (not merely validates) the fields the code - not the model
  - must supply outright (placement, obligation.level, vendorOnly), a
  deliberate, documented use of `output`'s own mutability. Catches
  `WorkItemFailed` in its own factory as the practical mechanism for
  Section 9.7's `[UNCERTAINTY]` "emit no candidate" behaviour, which
  `contracts/C8/CanonicalCandidate/1.0.json`'s all-required-fields
  schema has no direct way to represent.

- `mapping_generator.py` (Increment 9) - Mapping Generator (Appendix B),
  the twelfth and final agent. One invocation covers one whole region
  contract (the prompt's own `[INPUT]` block passes the complete,
  in-scope attribute list), a different granularity than ACORD
  Aligner/Canonical Synthesiser's own per-cluster calls - which is what
  makes G1 (Totality) a real, per-invocation guardrail here, implemented
  via `validate_semantics` since `Guardrail.check` has no access to the
  agent instance (the same framework constraint I8's own G1 checks
  already document). G2 (closed transform vocabulary) and G4 (lossy
  transform requires a note) reuse `mapping/parser.py`/
  `mapping/transforms.py` directly; G3 is deliberately the same rule as
  `mapping/compiler.py`'s own T2, restated as an early per-invocation
  gate. Unlike ACORD Aligner/Canonical Synthesiser's own worked prompts
  (both missing an `[INJECTION]` block, fixed at Increment 8), Appendix
  B's own prompt text already has a real one - no fix needed.
  `make_mapping_generator_factory(ctx)` is a factory, the same shape as
  `make_canonical_synthesiser_factory` - unlike that one, there is no
  legitimate "no output" outcome here (Rule 1's totality means every
  invocation must produce a full spec), so `WorkItemFailed` propagates
  to the caller rather than being caught and downgraded.

See `docs/increments.md` for what each increment built and verified
(including the real Anthropic API decision and the `tool.denied`
contract gap Increment 6 closed, Increment 7's empirically-found
clustering-weights fix, and Increment 8's two further contract gaps -
C7's missing `unassessed` verdict and C8's missing `vendorOnly` field),
and `tools/README.md` for the tool gateway these agents reach every
external capability through.
