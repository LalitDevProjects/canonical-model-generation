# eval

Agent evaluation harness (Section 16.4): "Agents are evaluated, not
asserted." Deferred at Increment 6 - no thresholds existed for Repository
Scout/Schema Interpreter, Section 16.4's own table names only Semantic
Resolver/ACORD Aligner/Canonical Synthesiser/Adversarial Critic/Rule
Extractor. Populated for real at Increment 7, where a real threshold
finally exists (Semantic Resolver).

- `thresholds.py` - `THRESHOLDS`, transcribed from Section 16.4's table
  for the agents this repo has actually built: Semantic Resolver's
  Cluster F1 (>= 0.88) and homonym recall (= 1.00, "no tolerance").
- `harness.py` - `EvalCase`/`EvalSet`/`EvalResult`, `evaluate()`/
  `score_one()`. Runs the FULL clustering pipeline (deterministic
  auto-merge + agent adjudication of the review-band material it sets
  aside) over an eval set and compares against each case's human-agreed
  expected outcome - not the agent in isolation, since that's not what a
  real deployment produces. Gated on the **worst** of `n_repeats` runs,
  not the mean, per Section 16.4's own literal `evaluate()` pseudocode
  ("the workshop sees one run, not an average"). `score_one` takes an
  injectable `adjudicate_factory` (the same DI convention as
  `gate/gate.py`/`substrate/ingest.py`/`agents/model_gateway.py`) rather
  than a hardcoded agent, so the harness's own arithmetic is proven
  hermetically against a scripted adjudicator - a real 5-repeat run
  against a live Anthropic model isn't reachable this session (no API
  key); one `pytest.mark.llm` test exercises the real
  `SemanticResolverAgent` end to end and skips cleanly.

See `docs/increments.md` for what Increment 7 built and verified.
