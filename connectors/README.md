# connectors

Populated at Increment 2.

- `base.py` — the `Connector` ABC (`discover`/`fetch`/`health`) and its
  supporting dataclasses (`ArtefactRef`, `RawArtefact`, `ConnectorScope`,
  `HealthStatus`), sized to what relevance filtering and manifest assembly
  need (Section 4.1 gives the ABC as pseudocode but leaves these shapes
  undefined).
- `git_connector.py` — `GitConnector`, reads an already-checked-out local
  git repository via real `git` CLI plumbing (`rev-parse`, `ls-tree`,
  `show`). Pins to a commit SHA.
- `confluence_connector.py` — `ConfluenceConnector`, reads local JSON
  fixtures shaped like a Confluence Cloud REST API page export. No real
  Confluence instance exists; this is a documented stand-in. Pins to the
  fixture's page `version.number`.
- `relevance.py` — `filter_relevance`: the two-pass relevance filter
  (Section 4.2). Pass 1 (deterministic scoring) is fully implemented; pass
  2 (the Repository Scout agent) doesn't exist until Increment 6, so the
  `uncertain` band defaults to kept via a swappable `scout_classifier`
  parameter.
- `manifest.py` — `assemble_corpus_manifest`: discover → filter → fetch →
  hash → seal into a schema-valid `C4Corpusmanifest`. `compute_corpus_hash`
  is the exact, documented sha256-over-sorted-content-hashes construction.

See `docs/increments.md` for what Increment 2 built and verified.
