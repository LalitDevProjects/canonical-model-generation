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

ACORD alignment scoring and coverage computation are not yet built - see
`docs/increments.md`.
