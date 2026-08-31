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
  `RunContext`, defined in `base.py`).
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

See `docs/increments.md` for what Increment 6 built and verified
(including the real Anthropic API decision and the `tool.denied`
contract gap it closed), and `tools/README.md` for the tool gateway
these agents reach every external capability through.
