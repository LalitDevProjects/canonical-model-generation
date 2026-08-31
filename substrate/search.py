"""
Hybrid retrieval (Section 6.4): "BM25 and vector similarity,
reciprocal-rank fused. Results are deterministically ordered by (score,
chunkHash) so that a replayed run retrieves the same context in the same
order."

BM25 is hand-written (a confirmed decision - no rank_bm25 dependency,
same bias as every prior increment's tooling choice); vector similarity
is a real pgvector `<=>` query. Both are computed as independent
{chunk_hash: score} rankings and fused in Python via reciprocal-rank
fusion - simpler to test each half independently than one fused SQL
statement, and keeps BM25 entirely out of SQL.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from substrate.embedding import vector_literal

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ChunkRow:
    chunk_hash: str
    text: str


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def bm25_scores(query: str, chunks: Sequence[ChunkRow], *, k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
    """Standard Okapi BM25 over the given chunk set (a run's own chunks,
    already filtered by region/kind/tier by the caller) - recomputing
    df/idf per call is fine at PoC scale (tens of artefacts)."""
    query_terms = _tokenize(query)
    if not query_terms or not chunks:
        return {}

    doc_tokens = {c.chunk_hash: _tokenize(c.text) for c in chunks}
    doc_lengths = {chunk_hash: len(terms) for chunk_hash, terms in doc_tokens.items()}
    avg_doc_length = sum(doc_lengths.values()) / len(doc_lengths) if doc_lengths else 0.0
    doc_count = len(chunks)

    unique_query_terms = set(query_terms)
    document_frequency: Counter[str] = Counter()
    for terms in doc_tokens.values():
        for term in unique_query_terms.intersection(terms):
            document_frequency[term] += 1

    inverse_document_frequency = {
        term: math.log(1 + (doc_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
        for term in unique_query_terms
    }

    scores: dict[str, float] = {}
    for chunk_hash, terms in doc_tokens.items():
        term_frequency = Counter(terms)
        doc_length = doc_lengths[chunk_hash]
        length_norm = 1.0 if avg_doc_length == 0 else doc_length / avg_doc_length
        score = 0.0
        for term in query_terms:
            frequency = term_frequency.get(term, 0)
            if frequency == 0:
                continue
            denominator = frequency + k1 * (1 - b + b * length_norm)
            score += inverse_document_frequency[term] * (frequency * (k1 + 1)) / denominator
        if score > 0:
            scores[chunk_hash] = score
    return scores


def vector_scores(
    conn: psycopg.Connection,
    run_id: UUID,
    query_embedding: list[float],
    *,
    region: str | None = None,
    artefact_kinds: list[str] | None = None,
    tier_max: int = 6,
    limit: int = 200,
) -> dict[str, float]:
    """Cosine similarity (1 - pgvector's `<=>` cosine distance) over
    `chunks`, restricted to this run and the caller's own filters. The
    SQL ORDER BY includes chunk_hash as a tie-break (not just the Python
    re-sort in rank_by_score) so that which rows survive `limit` is
    itself deterministic, not only their eventual display order."""
    conditions = ["run_id = %(run_id)s", "evidence_tier <= %(tier_max)s"]
    params: dict[str, object] = {
        "run_id": run_id,
        "tier_max": tier_max,
        "embedding": vector_literal(query_embedding),
        "limit": limit,
    }
    if region is not None:
        conditions.append("region = %(region)s")
        params["region"] = region
    if artefact_kinds:
        conditions.append("artefact_kind = ANY(%(kinds)s)")
        params["kinds"] = artefact_kinds
    where_clause = " AND ".join(conditions)

    rows = conn.execute(
        f"""
        SELECT chunk_hash, 1 - (embedding <=> %(embedding)s::vector) AS similarity
        FROM chunks
        WHERE {where_clause}
        ORDER BY embedding <=> %(embedding)s::vector, chunk_hash
        LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    return {row[0]: float(row[1]) for row in rows}


def rank_by_score(scores: dict[str, float]) -> list[str]:
    """(score DESC, chunk_hash ASC) - Section 6.4's own determinism
    requirement, applied both to an individual ranker's own ranking
    (before fusion assigns rank positions) and to the final fused
    result."""
    return [chunk_hash for chunk_hash, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def reciprocal_rank_fuse(*rankings: Sequence[str], k: int = 60) -> dict[str, float]:
    """fused(c) = sum over rankers of 1/(k + rank), 0 contribution from a
    ranker that never returned c at all. Each input ranking is expected
    to already be in (score, chunk_hash)-deterministic order (see
    rank_by_score) - reciprocal_rank_fuse itself doesn't re-sort its
    inputs, only assigns rank positions in the order given."""
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_hash in enumerate(ranking, start=1):
            fused[chunk_hash] += 1.0 / (k + rank)
    return dict(fused)
