# pipeline

Orchestration: run state persistence, checkpoints, and (built as work
beyond the 9-increment PoC guide) a real, hermetic driving orchestrator.

- `run_store.py` - `RunStore`, local-filesystem persistence at
  `run-store/{runId}/{stage}/...` (Section 3.7). Landed at Increment 2
  (ahead of a dedicated orchestration increment) because S1 "Corpus
  assembly" is a barrier stage and later increments need to read its
  sealed `CorpusManifest` back rather than re-running S1. `TriageEntry` +
  `append_triage_entry`/`read_triage_entries` (Increment 7) - the concrete
  "triage export" artefact Section 9.4's `emit_review_queue()` describes.
  Extended for `pipeline/orchestrator.py` and `api/run_control.py`:
  `write_run_manifest`/`read_run_manifest`/`update_run_state`/`list_runs`
  (C11 RunManifest itself was never persisted before, despite this
  module's own docstring naming its path since Increment 2),
  `read_journal_events` (no read-back existed before - only append and
  count), `write_clusters`/`read_clusters` and `write_candidates`/
  `read_candidates` (neither `ConceptCluster` nor `CanonicalCandidate`
  was persisted anywhere before), and generalised checkpoint sealing/
  decision recording (`seal_checkpoint`/`read_sealed_checkpoint`/
  `write_checkpoint_decisions`/`read_checkpoint_decisions`/
  `checkpoint_decisions_complete`) covering TRIAGE/RATIFY/ARB uniformly.
- `orchestrator.py` - `create_run()`/`resume_after_checkpoint()`. Drives
  a run synchronously, in-process, through exactly the stages that are
  already real and deterministic - S1 (real `GitConnector` instances over
  `golden/git/claims-{us,uk,eu}/`, sealed via `connectors.manifest.
  assemble_corpus_manifest` - the same real path
  `tests/connectors/test_golden_corpus_e2e.py` proves), S3 (real
  `parsers.router.parse` + `algorithms.profiling.profile` per artefact),
  S4 (real `algorithms.clustering.run_clustering`, "zero LLM dependency"
  by its own Increment 7 design) - then seals a real TRIAGE checkpoint
  and stops. No live Postgres, no live Anthropic key required for any of
  this. Only `domain="claims"` is wired to real golden-corpus data.
  `resume_after_checkpoint()` continues into ACORD Aligner (degrades
  automatically - licence disposition is never `permitted` in this repo)
  and Canonical Synthesiser only if a real model provider is configured;
  otherwise the run stops at `AWAIT_MODEL_PROVIDER`, honestly labelled,
  never faking a decision. Semantic Resolver's own review-band
  adjudication is deliberately NOT part of this continuation - discovered
  empirically while building this module: `agents/semantic_resolver.py`'s
  own `assemble_context()` calls `SubstrateApi.search()`, which needs a
  live DB connection this continuation does not otherwise require: review-
  band material stays exactly as `create_run()` sealed it. Mapping
  generation is likewise not automatic - it has no natural home in a
  run-scoped continuation.
- `registry_store.py` - `RegistryStore` (built alongside `orchestrator.py`),
  file-based persistence for signed `emit.release.ReleaseManifest`s per
  domain+semver, plus the raw artefact bytes a release references. Same
  directory-per-key convention as `RunStore`.
- `workshop_store.py` - `WorkshopStore` (same), workshop records and the
  decisions captured against them. Deliberately does not duplicate
  `emit.workshop_pack.assemble_pack`'s own pack-writing logic -
  `pack_dir(workshop_id)` is handed directly to that function as its
  `output_dir`.

See `api/README.md` for the HTTP layer these stores and the orchestrator
sit behind, and `docs/increments.md` for the full build record.
