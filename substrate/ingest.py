"""
The substrate ingestion orchestrator (Section 6, in full): the first
place parsers/router.py (built at Increment 3) is actually run against
admitted artefacts and its output persisted, alongside the wholly new
chunking + embedding + graph write paths this increment adds. Mirrors
gate/gate.py::classify_and_redact's own shape (a pure orchestrator,
explicit kwargs, a frozen-dataclass result) and
connectors/manifest.py::assemble_corpus_manifest's discover->...->seal
pipeline structure.

Reads each admitted artefact's REDACTED content from the evidence store
(evidence_store.read_artefact(contentHash)) - never re-fetches raw bytes
from a connector. The gate already redacted this content once at
Increment 4; re-deriving from raw bytes here would silently reintroduce
the PII the gate removed.

parsers/router.py::parse() raises ValueError for any mediaType with no
registered parser (Confluence has none - verified by reading the file:
it's documentary evidence only, by design). That failure is caught here
and treated as "this artefact contributes no attributes", not as a fatal
ingestion error - only the router's own "no parser registered" message
is expected to raise ValueError at this call site; a genuine parse
failure inside a registered parser would surface as a different
exception type and propagate, which is the correct behaviour for an
admitted artefact that fails to parse.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from gate.evidence_store import EvidenceStore
from parsers.router import parse
from pipeline.run_store import RunStore
from substrate.chunking import chunk
from substrate.db import SubstrateDb
from substrate.embedding import MOCK_MODEL_ID, mock_embed, vector_literal
from substrate.graph import edge_attribute_evidenced_by, node_from_artefact, node_from_attribute, write_edge, write_node


def _default_embed(text: str, dimensions: int) -> list[float]:
    return mock_embed(text, dimensions=dimensions)


def _parse_or_skip(content: bytes, artefact: C1Sourceartefact, run_id: UUID) -> list[C5Attributerecord]:
    try:
        return parse(content, artefact, run_id)
    except ValueError:
        return []


def attribute_embedding_text(record: C5Attributerecord) -> str:
    """"Embedding neighbourhood over name + description" (Section 6.4's
    neighbours() docstring). Public since Increment 7:
    algorithms/similarity.py recomputes the same embedding locally
    (algorithms/ has no DB dependency), and must use the exact same text
    basis this module used when the vector was first stored, or the two
    would silently diverge."""
    description = record.semantics.description if record.semantics else None
    return f"{record.localName} {description}" if description else record.localName


@dataclass(frozen=True)
class IngestResult:
    attributes_written: int
    chunks_written: int
    chunks_skipped_idempotent: int
    nodes_written: int
    edges_written: int


def ingest_artefacts(
    run_id: UUID,
    manifest: C4Corpusmanifest,
    *,
    evidence_store: EvidenceStore,
    run_store: RunStore,
    db: SubstrateDb,
    dimensions: int,
    embed_fn: Callable[[str, int], list[float]] = _default_embed,
    embedding_model_id: str = MOCK_MODEL_ID,
) -> IngestResult:
    attributes_by_region: dict[str, list[C5Attributerecord]] = defaultdict(list)
    chunks_written = 0
    chunks_skipped_idempotent = 0
    nodes_written = 0
    edges_written = 0

    with db.connection() as conn:
        for artefact in manifest.artefacts:
            content = evidence_store.read_artefact(artefact.contentHash)

            artefact_node_id, artefact_node_type, artefact_props = node_from_artefact(artefact)
            write_node(conn, artefact_node_id, artefact_node_type, artefact_props, run_id=str(run_id))
            nodes_written += 1

            for record in _parse_or_skip(content, artefact, run_id):
                attributes_by_region[record.region.value].append(record)

                attr_node_id, attr_node_type, attr_props = node_from_attribute(record)
                write_node(conn, attr_node_id, attr_node_type, attr_props, run_id=str(run_id))
                nodes_written += 1

                from_id, to_id, edge_type = edge_attribute_evidenced_by(record)
                write_edge(conn, from_id, to_id, edge_type)
                edges_written += 1

                attribute_vector = embed_fn(attribute_embedding_text(record), dimensions)
                conn.execute(
                    """
                    INSERT INTO attribute_embeddings (attribute_id, run_id, embedding, embedding_model_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (attribute_id) DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        embedding = EXCLUDED.embedding,
                        embedding_model_id = EXCLUDED.embedding_model_id
                    """,
                    (record.attributeId, run_id, vector_literal(attribute_vector), embedding_model_id),
                )

            for draft in chunk(content, artefact):
                already_present = conn.execute(
                    "SELECT 1 FROM chunks WHERE chunk_hash = %s", (draft.chunk_hash,)
                ).fetchone()
                if already_present is not None:
                    # Section 6.2's literal idempotency requirement: an
                    # unchanged chunk skips the embedding call entirely,
                    # not merely the write - embed_fn is never called
                    # below for this draft.
                    chunks_skipped_idempotent += 1
                    continue

                chunk_vector = embed_fn(draft.text, dimensions)
                conn.execute(
                    """
                    INSERT INTO chunks
                        (chunk_hash, run_id, artefact_id, content_hash, evref, region,
                         artefact_kind, evidence_tier, chunk_text, embedding, embedding_model_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_hash) DO NOTHING
                    """,
                    (
                        draft.chunk_hash, run_id, draft.artefact_id, draft.content_hash, draft.evref,
                        draft.region, draft.artefact_kind, draft.evidence_tier, draft.text,
                        vector_literal(chunk_vector), embedding_model_id,
                    ),
                )
                chunks_written += 1

    for region, records in attributes_by_region.items():
        run_store.write_attributes(run_id, region, records)

    return IngestResult(
        attributes_written=sum(len(records) for records in attributes_by_region.values()),
        chunks_written=chunks_written,
        chunks_skipped_idempotent=chunks_skipped_idempotent,
        nodes_written=nodes_written,
        edges_written=edges_written,
    )
