-- The knowledge substrate's own stores (Section 6.1: "three views of the
-- same evidence - the raw artefacts, a chunk-level vector index for
-- retrieval, and a graph of concepts and their lineage - behind one
-- read-only, run-scoped API"). Derived data, not primary evidence -
-- Section 6's own framing licenses idempotent upsert writes: "may be
-- dropped and reconstructed from the evidence store."
--
-- {dimensions} is substituted by substrate/db.py::SubstrateDb.ensure_schema
-- before this file is executed - a pgvector column's dimension must be a
-- literal at CREATE TABLE time, and the real value
-- (config.models.embedding_dimensions, 1024 in production) is only known
-- at runtime; tests use a much smaller dimension for speed.

CREATE EXTENSION IF NOT EXISTS vector;

-- Section 6.2: "Every chunk carries artefactId, contentHash, evref
-- locator, region, evidenceTier and chunkHash. Chunk identity is the
-- SHA-256 of normalised content, which makes embedding idempotent:
-- re-ingesting an unchanged artefact produces identical chunk hashes and
-- skips the embedding call entirely." chunk_hash is therefore the
-- primary key, not a surrogate id.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_hash          CHAR(64) PRIMARY KEY,
    run_id               UUID NOT NULL,
    artefact_id          TEXT NOT NULL,
    content_hash         CHAR(64) NOT NULL,
    evref                TEXT NOT NULL,
    region               TEXT NOT NULL,
    artefact_kind        TEXT NOT NULL,
    evidence_tier        SMALLINT NOT NULL CHECK (evidence_tier BETWEEN 1 AND 6),
    chunk_text           TEXT NOT NULL,
    embedding             vector({dimensions}) NOT NULL,
    embedding_model_id    TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_run_region_kind ON chunks (run_id, region, artefact_kind);

-- Section 6.4: neighbours() is "embedding neighbourhood over name +
-- description" - a builder decision (no storage shape given in the
-- spec's pseudocode) to give it a concrete home, keyed by attributeId
-- since attribute embeddings are looked up by attribute, not searched
-- freehand the way chunks are.
CREATE TABLE IF NOT EXISTS attribute_embeddings (
    attribute_id          TEXT PRIMARY KEY,
    run_id                 UUID NOT NULL,
    embedding               vector({dimensions}) NOT NULL,
    embedding_model_id      TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_attr_emb_run ON attribute_embeddings (run_id);

-- The concept graph (Section 6.3), as a generic property graph rather
-- than one physical table per node/edge type: the four-hop lineage
-- query walks heterogeneously-typed hops
-- (Attribute -> Cluster -> AcordConcept/Candidate -> Decision/Release),
-- which a single recursive CTE over two tables expresses directly - the
-- typed-table alternative would need a large UNION ALL across 7 node
-- tables x 7 edge tables for no benefit at this scale ("the traversals
-- required are shallow, which is why PostgreSQL with recursive CTEs is
-- an acceptable starting implementation" - Section 6.3).
--
-- node_id is always the real contract's own id (artefactId/attributeId/
-- clusterId/candidateId for Artefact/Attribute/Cluster/Candidate - never
-- a parallel identifier); AcordConcept/Release/Decision have no
-- C-numbered contract anywhere (Section 6.3 introduces them fresh) so
-- their node_id is a builder-assigned string (see substrate/graph.py).
CREATE TABLE IF NOT EXISTS nodes (
    node_id      TEXT PRIMARY KEY,
    node_type    TEXT NOT NULL CHECK (node_type IN
                   ('Artefact', 'Attribute', 'Cluster', 'AcordConcept', 'Candidate', 'Release', 'Decision')),
    run_id       UUID,
    properties   JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_nodes_type_run ON nodes (node_type, run_id);

CREATE TABLE IF NOT EXISTS edges (
    from_id     TEXT NOT NULL REFERENCES nodes (node_id),
    to_id       TEXT NOT NULL REFERENCES nodes (node_id),
    edge_type   TEXT NOT NULL CHECK (edge_type IN
                  ('EVIDENCED_BY', 'MEMBER_OF', 'ALIGNS_TO', 'PRODUCED', 'RATIFIED_BY', 'RELEASED_IN', 'SUPERSEDES')),
    properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_id, to_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges (from_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges (to_id, edge_type);
