"""
Blocking (Section 9.2 - "Core Algorithms"). "A naive all-pairs comparison
over an estate of this size is quadratic and unaffordable. Blocking
reduces the comparison set to pairs with a plausible chance of matching."

Three independent blocking keys, matching the spec's own build_blocks()
exactly: head-noun (by_head), coarse type family + head-noun prefix
(by_type), and embedding neighbourhood (by_embedding, DB-backed via
SubstrateApi.neighbours - Increment 5). "An attribute may appear in
several blocks; overlap is intended, because any single key has blind
spots."

The versioned abbreviation dictionary ("domain-specific and grows during
the PoC; it is versioned as configuration, not code") lives in
config/platform.yaml's clustering.abbreviations, not here - see
config/settings.py::ClusteringConfig.

canonical_tokens/head_noun themselves stay in algorithms/profiling.py
(Increment 3) - this module calls them with real abbreviations/
lemmatise_fn/prefer arguments rather than duplicating a second tokenizer.
The head_noun "prefer" set (TYPE_NOUN_TOKENS) is what lets e.g.
"dateOfLoss" head on "date" like "lossDate" does, rather than on the
positionally-last "loss" - assembled from the abbreviation dictionary's
own values plus profiling.py's existing TEMPORAL_TOKENS/MONETARY_TOKENS,
not a new invented list.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from config.settings import ClusteringConfig
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.profiling import MONETARY_TOKENS, TEMPORAL_TOKENS, ProfiledAttribute, canonical_tokens, head_noun


@dataclass(frozen=True)
class Block:
    members: tuple[ProfiledAttribute, ...]
    anchor: ProfiledAttribute | None = None


def type_noun_tokens(config: ClusteringConfig) -> frozenset[str]:
    """The set of tokens head_noun() should prefer over strict
    positional last-token when blocking: every abbreviation's expansion
    (config-driven, e.g. "dt" -> "date") plus profiling.py's own
    temporal/monetary token sets."""
    return frozenset(config.abbreviations.values()) | TEMPORAL_TOKENS | MONETARY_TOKENS


def lemmatise(token: str) -> str:
    """Porter-lite suffix stripping - not a real lemmatiser, sufficient
    for this PoC's blocking-key normalisation (e.g. "amounts" ->
    "amount", "policies" -> "policy"). Guards on minimum length so short
    genuine words (e.g. "loss", "sum") are never over-stripped."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "xes", "zes", "ses")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    if len(token) > 6 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 5 and token.endswith("ed"):
        return token[:-2]
    return token


def _blocking_head_noun(attr: ProfiledAttribute, config: ClusteringConfig, prefer: frozenset[str]) -> str:
    tokens = canonical_tokens(attr.record.localName, abbreviations=config.abbreviations, lemmatise_fn=lemmatise)
    return head_noun(tokens, prefer=prefer)


class NeighboursApi(Protocol):
    """The subset of substrate.api.SubstrateApi that build_blocks needs,
    as a structural Protocol so algorithms/ never imports substrate/
    (algorithms stays a pure, DB-free package; only the caller wiring a
    real run needs a real SubstrateApi instance)."""

    def neighbours(self, run_id: str, attribute_id: str, *, top_k: int = 25) -> list[C5Attributerecord]: ...


def build_blocks(
    attrs: Sequence[ProfiledAttribute],
    *,
    run_id: str | None = None,
    api: NeighboursApi | None = None,
    config: ClusteringConfig,
) -> list[Block]:
    """Section 9.2's build_blocks(), against this repo's real
    ProfiledAttribute/SubstrateApi shapes. api/run_id are optional and
    must be supplied together: when absent, the by_embedding key
    degrades to empty (documented, non-fatal - "any single key has blind
    spots" is the spec's own framing) rather than requiring a live
    Postgres connection for a pure-algorithm call. A pytest.mark.db test
    proves the embedding key for real."""
    prefer = type_noun_tokens(config)
    by_id = {a.record.attributeId: a for a in attrs}
    blocking_head = {a.record.attributeId: _blocking_head_noun(a, config, prefer) for a in attrs}

    by_head: dict[str, list[ProfiledAttribute]] = defaultdict(list)
    by_type: dict[tuple[str, str], list[ProfiledAttribute]] = defaultdict(list)
    for a in attrs:
        head = blocking_head[a.record.attributeId]
        by_head[head].append(a)
        by_type[(a.type_family, head[:3])].append(a)

    by_embedding: list[Block] = []
    if api is not None and run_id is not None:
        for a in attrs:
            neighbour_records = api.neighbours(run_id, a.record.attributeId, top_k=config.block_top_k)
            neighbour_attrs = [by_id[r.attributeId] for r in neighbour_records if r.attributeId in by_id]
            if neighbour_attrs:
                # The anchor is included in members (the pseudocode's own
                # Block(anchor=a, members=neighbours) would otherwise
                # never compare a to its own neighbours downstream).
                by_embedding.append(Block(anchor=a, members=(a, *neighbour_attrs)))

    blocks = (
        [Block(members=tuple(v)) for v in by_head.values() if len(v) > 1]
        + [Block(members=tuple(v)) for v in by_type.values() if len(v) > 1]
        + by_embedding
    )
    return dedupe_blocks(blocks, max_size=config.block_max_size)


def dedupe_blocks(blocks: list[Block], *, max_size: int) -> list[Block]:
    """Merge/dedupe overlapping blocks by exact member-set (drop repeats
    across the three strategies, keep first occurrence), then cap any
    surviving block at max_size (Section 8.6's prompt-size ceiling) via
    deterministic attributeId-sorted truncation - simple and
    reproducible, not relevance-ranked."""
    seen: set[frozenset[str]] = set()
    result: list[Block] = []
    for block in blocks:
        key = frozenset(m.record.attributeId for m in block.members)
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        if len(block.members) > max_size:
            truncated = tuple(sorted(block.members, key=lambda m: m.record.attributeId)[:max_size])
            result.append(Block(members=truncated, anchor=block.anchor))
        else:
            result.append(block)
    return result
