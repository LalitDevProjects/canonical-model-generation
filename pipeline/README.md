# pipeline

Orchestration: run state machine, work items, checkpoints - built
alongside I2-I9, populated incrementally.

- `run_store.py` — `RunStore`, minimal local-filesystem persistence for
  sealed stage output at `run-store/{runId}/{stage}/...` (Section 3.7).
  Landed at Increment 2 (ahead of a dedicated orchestration increment)
  because S1 "Corpus assembly" is a barrier stage and later increments
  need to read its sealed `CorpusManifest` back rather than re-running S1.
  Not a general registry - just enough to write/read one sealed document
  per stage. `TriageEntry` + `append_triage_entry`/`read_triage_entries`
  (Increment 7) - the concrete "triage export" artefact Section 9.4's
  `emit_review_queue()` describes (`run-store/{runId}/S4/triage.jsonl`,
  append-only, since entries accumulate from both the deterministic
  review queue and later Semantic Resolver escalations) - **not** the
  full Section 12.1 run-control API or Section 8.4 `AWAIT_*` checkpoint
  machinery, which stay out of scope (same precedent as Increment 6's
  orchestrator deferral).

The run state machine itself (S1-S8 transitions, checkpoints, work-item
fan-out) is not yet built - see `docs/increments.md`.
