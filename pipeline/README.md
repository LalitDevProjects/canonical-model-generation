# pipeline

Orchestration: run state machine, work items, checkpoints - built
alongside I2-I9, populated incrementally.

- `run_store.py` — `RunStore`, minimal local-filesystem persistence for
  sealed stage output at `run-store/{runId}/{stage}/...` (Section 3.7).
  Landed at Increment 2 (ahead of a dedicated orchestration increment)
  because S1 "Corpus assembly" is a barrier stage and later increments
  need to read its sealed `CorpusManifest` back rather than re-running S1.
  Not a general registry - just enough to write/read one sealed document
  per stage.

The run state machine itself (S1-S8 transitions, checkpoints, work-item
fan-out) is not yet built - see `docs/increments.md`.
