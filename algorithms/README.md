# algorithms

Section 9 "Core Algorithms": attribute profiling, blocking, similarity
scoring, clustering, conflict classification, ACORD alignment scoring,
coverage computation.

- `profiling.py` — populated at Increment 3, ahead of the rest of this
  directory (blocking/clustering land at Increments 7-8). Landed early
  because Increment 3's own acceptance test needs it directly ("the
  untyped date raises type-suspicion") - the same precedent Increment 2
  used to land `pipeline/run_store.py` ahead of `pipeline/`'s own named
  increment. `profile()` implements Section 9.1's pseudocode exactly;
  `canonical_tokens`/`head_noun`/`TYPE_FAMILY`/`looks_temporal`/
  `looks_monetary`/`documented_values` are deliberately minimal,
  provisional heuristics - the versioned abbreviation dictionary Section
  9.2 describes belongs to Increment 7's blocking work, not this one.

Blocking, similarity, clustering, homonym splitting, ACORD alignment, and
coverage computation are not yet built - see `docs/increments.md`.
