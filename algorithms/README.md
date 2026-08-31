# algorithms

Section 9 "Core Algorithms": attribute profiling, blocking, similarity
scoring, clustering, conflict classification, ACORD alignment scoring,
coverage computation.

- `profiling.py` — populated at Increment 3. `profile()` implements
  Section 9.1's pseudocode exactly. `canonical_tokens`/`head_noun` gained
  optional `abbreviations`/`lemmatise_fn`/`prefer` parameters at
  Increment 7 (all defaulting to Increment 3's exact behaviour -
  `profile()` itself still calls them with none of the new arguments);
  `blocking.py` is the only caller that supplies real ones. `TEMPORAL_TOKENS`/
  `MONETARY_TOKENS` were promoted to public at Increment 7 for reuse by
  `blocking.py`'s own head-noun preference set.
- `blocking.py` (Increment 7) — Section 9.2's `build_blocks()`: three
  independent keys (by-head, by-type, and an optional DB-backed
  by-embedding key via `SubstrateApi.neighbours` - degrades to empty,
  not fatal, when `api`/`run_id` are omitted). The versioned abbreviation
  dictionary lives in `config/platform.yaml`'s `clustering.abbreviations`,
  not here. `dedupe_blocks()` (exact-duplicate collapse + deterministic
  truncation at `block_max_size`, Section 8.6's prompt-size ceiling).
  `lemmatise()` is a documented "Porter-lite" suffix stripper, not a real
  lemmatiser.
- `similarity.py` (Increment 7) — Section 9.3's `similarity()`, against
  this repo's real `ProfiledAttribute`/`ClusteringConfig` shapes.
  `embeddings` is an explicit `dict[attributeId, vector]` parameter (from
  `compute_embeddings()`), a documented deviation from the pseudocode's
  literal `a.embedding` attribute access - `ProfiledAttribute` itself
  carries no embedding field. `type_compatibility()` resolves same-type
  pairs to 1.0 even when the configured table doesn't happen to
  enumerate that exact pair (a documented correction - the table's own
  "deliberately not equality" framing is about the *divergent* pairs it
  lists). `pattern_range_similarity()` does real interval-overlap math
  for range/length constraints. See `config/settings.py::ClusteringConfig.weights`
  for why the default weights are NOT the spec's literal
  0.20/0.30/0.15/0.20/0.15 (this PoC's mock, non-semantic embedding
  provider makes the spec's own 0.30 embedding weight make
  `LINK_THRESHOLD` structurally unreachable - an empirically-found and
  fixed problem, not a hypothetical one).
- `graph.py` (Increment 7) — hand-rolled BFS connected components. No
  third-party graph-library dependency: every dependency this repo has
  added so far was load-bearing/non-substitutable, and PoC block sizes
  (`<=40` members) make this trivial to hand-write.
- `conflict.py` (Increment 7) — Section 9.5's full taxonomy.
  `HOMONYM_SIGNALS`/`split_on_homonym_signals()`/`min_cut_until()` (a
  documented greedy lowest-edge-removal partition, explicitly not
  Stoer-Wagner). `classify_conflict()` covers the remaining four classes
  (granularity/type/enumeration/obligation). `contradiction_detected` is
  an honest permanent stub - the spec ties it to "critic-assessed,
  cached," and the Adversarial Critic agent doesn't exist until
  Increment 8/9 (same status as `substrate/api.py::acord_lookup`'s
  empty-list precedent).
- `clustering.py` (Increment 7) — `run_clustering()`, the full
  deterministic pipeline (blocking -> similarity -> connected-components
  -> homonym split -> conflict classification -> real
  `generated.C6.ConceptCluster` objects). Fully self-sufficient with
  zero LLM dependency - the Semantic Resolver agent
  (`agents/semantic_resolver.py`) adjudicates only the review-band
  material this module sets aside. `build_cluster()`'s role/confidence/
  proposedConcept rules are documented, provisional heuristics pending a
  real synthesis pass (Increment 8/9). `write_triage_export()` +
  `pipeline/run_store.py::TriageEntry` are the concrete "triage export"
  deliverable - not the full run-control API or checkpoint machinery,
  which stay out of scope (matching Increment 6's orchestrator-deferral
  precedent).

- `naming.py` (Increment 8) — Section 9.9's `check_name()` verbatim,
  reusing `algorithms.profiling.canonical_tokens`/
  `config.settings.ClusteringConfig.abbreviations` directly rather than
  a third tokenisation implementation. `NamingViolation` is a local,
  2-field shape (`kind`, `message`) matching the spec's own pseudocode
  literally - not `agents.validation.Violation` (a different, 4-field
  framework shape); `agents/canonical_synthesiser.py`'s own G2 guardrail
  adapts between the two.
- `placement.py` (Increment 8) — Section 9.7's `place()` verbatim: "the
  agent writes the rationale; this function decides." `PlacementContext`'s
  three workshop-decision callables all default to `False` ("never
  guess" - no workshop-decision-recording mechanism exists in this
  repo). Called from within `agents/canonical_synthesiser.py`'s own
  flow, not a separate agent - see that module's docstring for why no
  standalone "Extension Partitioner" agent exists.
- `coverage.py` (Increment 8) — Section 9.8's `coverage()` and the gap
  register (`gap_register()`), Increment 8's own named deliverable
  distinct from `coverage()` itself. `Concept` is one per `ConceptCluster`
  (not per candidate) - a cluster with no synthesised candidate becomes
  a `"gap"` concept, the spec's own named category. No agent wrapper
  exists ("Coverage Scorer... Pure arithmetic," §7.7) - called directly,
  the same "no orchestrator needed" precedent as Increment 7's
  `run_clustering()`.

See `docs/increments.md` for what Increment 8 built and verified.
