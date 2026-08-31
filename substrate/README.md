# substrate

Populated at Increment 5. The knowledge substrate (Section 6): a
chunk-level vector index and a concept graph, both behind one read-only,
run-scoped `SubstrateApi`, backed by real PostgreSQL + pgvector
(`infra/docker-compose.yml`, built at Increment 1 specifically
anticipating this).

- `db.py` - `SubstrateDb`: connection handling, idempotent schema
  creation. Mirrors `pipeline/run_store.py`'s `RunStore` constructor
  pattern, except a DSN has no repo-relative "sensible default" the way
  a filesystem path does, so `dsn` is a required parameter rather than
  defaulting to `config.storage.postgres_dsn` internally.
- `schema.sql` - `nodes`/`edges` (a generic property graph, not one
  table per node/edge type - see its own docstring for the full
  reasoning) and `chunks`/`attribute_embeddings` (pgvector columns).
- `chunking.py` - per-artefact-kind chunkers (Section 6.2): one chunk
  per named schema component for OpenAPI/JSON Schema (`$ref` closure
  inlined to depth 1), per complex type or operation for XSD/WSDL
  (inherited members inlined), heading-boundary splits for Confluence.
  Avro is absent from the spec's own table - `chunk_avro`'s "one chunk
  per named record/enum/fixed" is a documented builder default. Source
  code and the ACORD reference pack are confirmed out of scope, same
  status as `parsers/code_inference.py`.
- `embedding.py` - `mock_embed()`: a deterministic, non-semantic
  placeholder for Increment 6's real model gateway (locked in at
  Increment 1: "backed by a mock provider until Increment 6"). Neither
  of this increment's own acceptance-test clauses needs semantic
  meaning, only reproducibility.
- `graph.py` - node/edge writes (idempotent upserts - Section 6's own
  framing: this data is "derived; may be dropped and reconstructed from
  the evidence store") and `lineage()`, a recursive CTE answering the
  spec's own worked query: "Which regional artefacts, at which versions,
  support canonical attribute X in release 1.0, and who ratified it?"
  `AcordConcept`/`Release`/`Decision` have no C-numbered contract
  anywhere (Section 6.3 introduces them fresh) - their properties are
  plain frozen dataclasses here, the same status as
  `algorithms/profiling.py`'s `Finding`.
- `search.py` - hand-written BM25 (no `rank_bm25` dependency, same bias
  as every prior increment's tooling choice) and reciprocal-rank fusion.
  `rank_by_score`'s `(score, chunk_hash)` tie-break is what makes
  `search()`'s ordering genuinely deterministic across repeats, not just
  usually so.
- `ingest.py` - `ingest_artefacts`: the first place `parsers/router.py`
  (built at Increment 3) is actually run against admitted artefacts and
  its output persisted. Reads each artefact's REDACTED content from the
  evidence store, never re-fetches raw bytes from a connector - the gate
  already redacted this content once at Increment 4.
- `api.py` - `SubstrateApi`, Section 6.4's five methods verbatim
  (`search`/`get_attribute`/`neighbours`/`acord_lookup`/`lineage`)
  against this repo's real generated contracts.

See `docs/increments.md` for what Increment 5 built and verified, and
`docs/contracts.md` for why `AcordConcept`/`Release`/`Decision` are
graph-native properties rather than new JSON Schema contracts.
