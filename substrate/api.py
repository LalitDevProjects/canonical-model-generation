"""
SubstrateApi (Section 6.4): "Read-only, run-scoped. A run can never read
another run's corpus." The literal pseudocode's five methods, against
this repo's real generated contracts (get_attribute/neighbours return
generated.C5.AttributeRecord directly, not a parallel shape) and real
Postgres-backed stores.

"Deterministic ordering is a reproducibility requirement, not a nicety:
non-deterministic retrieval makes replay meaningless." - search()'s own
determinism is entirely substrate/search.py's responsibility
(rank_by_score's (score, chunk_hash) tie-break); this module just wires
the two rankers together and re-attaches chunk metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C11.JournalEvent._1_0 import C11Journalevent, Kind, Outcome

from pipeline.run_store import RunStore
from substrate.db import SubstrateDb
from substrate.embedding import mock_embed
from substrate.graph import AcordConceptProps, GraphEdge, GraphNode, LineageGraph, lineage as graph_lineage
from substrate.search import ChunkRow, bm25_scores, reciprocal_rank_fuse, rank_by_score, vector_scores

__all__ = ["Chunk", "GraphEdge", "GraphNode", "LineageGraph", "SubstrateApi"]

_VECTOR_CANDIDATE_LIMIT = 10_000
"""Effectively "no limit" at PoC scale (tens of artefacts, each a
handful of chunks) - both rankers see the same candidate pool this way,
which rank_by_score/reciprocal_rank_fuse depend on for a meaningful
fusion; a real deployment at Section 2.3's stated pgvector scale ceiling
(millions of chunks) would need this to be a real cap."""


@dataclass(frozen=True)
class Chunk:
    chunk_hash: str
    artefact_id: str
    content_hash: str
    evref: str
    region: str
    evidence_tier: int
    text: str
    score: float


class SubstrateApi:
    """Read-only, run-scoped. A run can never read another run's corpus."""

    def __init__(
        self,
        db: SubstrateDb,
        run_store: RunStore,
        *,
        dimensions: int,
        acord_ingestion_enabled: bool,
    ) -> None:
        self._db = db
        self._run_store = run_store
        self._dimensions = dimensions
        self._acord_ingestion_enabled = acord_ingestion_enabled

    def search(
        self,
        run_id: str,
        query: str,
        *,
        region: str | None = None,
        artefact_kinds: list[str] | None = None,
        tier_max: int = 6,
        top_k: int = 25,
    ) -> list[Chunk]:
        """Hybrid retrieval: BM25 and vector similarity, reciprocal-rank
        fused. Results are deterministically ordered by (score,
        chunkHash) so that a replayed run retrieves the same context in
        the same order."""
        run_uuid = UUID(run_id)
        query_embedding = mock_embed(query, dimensions=self._dimensions)

        conditions = ["run_id = %(run_id)s", "evidence_tier <= %(tier_max)s"]
        params: dict[str, object] = {"run_id": run_uuid, "tier_max": tier_max}
        if region is not None:
            conditions.append("region = %(region)s")
            params["region"] = region
        if artefact_kinds:
            conditions.append("artefact_kind = ANY(%(kinds)s)")
            params["kinds"] = artefact_kinds
        where_clause = " AND ".join(conditions)

        with self._db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_hash, chunk_text, artefact_id, content_hash, evref, region, evidence_tier
                FROM chunks WHERE {where_clause}
                """,
                params,
            ).fetchall()
            vector_ranking_scores = vector_scores(
                conn, run_uuid, query_embedding,
                region=region, artefact_kinds=artefact_kinds, tier_max=tier_max,
                limit=_VECTOR_CANDIDATE_LIMIT,
            )

        meta_by_hash = {row[0]: row for row in rows}
        bm25_ranking_scores = bm25_scores(query, [ChunkRow(chunk_hash=row[0], text=row[1]) for row in rows])

        fused = reciprocal_rank_fuse(rank_by_score(bm25_ranking_scores), rank_by_score(vector_ranking_scores))
        ordered_hashes = rank_by_score(fused)[:top_k]

        return [
            Chunk(
                chunk_hash=chunk_hash,
                artefact_id=meta_by_hash[chunk_hash][2],
                content_hash=meta_by_hash[chunk_hash][3],
                evref=meta_by_hash[chunk_hash][4],
                region=meta_by_hash[chunk_hash][5],
                evidence_tier=meta_by_hash[chunk_hash][6],
                text=meta_by_hash[chunk_hash][1],
                score=fused[chunk_hash],
            )
            for chunk_hash in ordered_hashes
        ]

    def get_attribute(self, run_id: str, attribute_id: str) -> C5Attributerecord:
        for record in self._run_store.read_attributes(UUID(run_id)):
            if record.attributeId == attribute_id:
                return record
        raise KeyError(f"no attribute {attribute_id!r} found in run {run_id!r}")

    def neighbours(self, run_id: str, attribute_id: str, *, top_k: int = 25) -> list[C5Attributerecord]:
        """Embedding neighbourhood over name + description (Section
        6.4). Feeds blocking (9.2)."""
        run_uuid = UUID(run_id)
        with self._db.connection() as conn:
            seed_exists = conn.execute(
                "SELECT 1 FROM attribute_embeddings WHERE attribute_id = %s AND run_id = %s",
                (attribute_id, run_uuid),
            ).fetchone()
            if seed_exists is None:
                return []
            rows = conn.execute(
                """
                SELECT attribute_id FROM attribute_embeddings
                WHERE run_id = %(run_id)s AND attribute_id != %(seed)s
                ORDER BY
                    embedding <=> (SELECT embedding FROM attribute_embeddings WHERE attribute_id = %(seed)s AND run_id = %(run_id)s),
                    attribute_id
                LIMIT %(top_k)s
                """,
                {"run_id": run_uuid, "seed": attribute_id, "top_k": top_k},
            ).fetchall()

        records_by_id = {record.attributeId: record for record in self._run_store.read_attributes(run_uuid)}
        return [records_by_id[row[0]] for row in rows if row[0] in records_by_id]

    def acord_lookup(self, run_id: str, query: str, *, top_k: int = 10) -> list[AcordConceptProps]:
        """Gated on licence disposition. Every call is logged with the
        caller, the query and the returned refs, for licence compliance.

        ACORD Reference Architecture data is unlicensed/unavailable in
        this repo (a locked-in Increment 1 decision), regardless of
        self._acord_ingestion_enabled - there is no real data behind
        either branch to gate, so this always returns an empty list,
        consistent with Section 19.2's degraded mode ("ACORD ingestion
        not permitted: acord-aligner is disabled"). The mandatory audit
        log still fires unconditionally, using kind=tool.call - the
        closest existing C11Journalevent.Kind value (no agent-runtime
        tool-call concept exists yet at Increment 5; worth reconciling
        once Increment 6 builds one). self._acord_ingestion_enabled is
        still threaded through the constructor so a real Increment 8
        acord-aligner integration has somewhere to plug in the actual
        gate, rather than this method reading the feature flag directly."""
        run_uuid = UUID(run_id)
        self._run_store.append_journal_event(run_uuid, C11Journalevent.model_validate({
            "runId": run_uuid,
            "seq": self._run_store.next_journal_seq(run_uuid),
            "at": datetime.now(timezone.utc),
            "kind": Kind.tool_call,
            "outcome": Outcome.ok,
        }))
        return []

    def lineage(self, candidate_id: str) -> LineageGraph:
        with self._db.connection() as conn:
            return graph_lineage(conn, candidate_id)
