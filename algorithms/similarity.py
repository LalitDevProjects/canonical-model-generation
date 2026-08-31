"""
Similarity scoring (Section 9.3 - "Core Algorithms"). similarity(a, b)
combines five features - lexical, embedding, type, constraints, context -
into one weighted score, returning the per-feature breakdown alongside it
(needed by build_cluster() to explain a merge/split, and by the Semantic
Resolver's own review-band input).

"Weights and the compatibility matrix are configuration pinned in the run
manifest, so a weight change is a visible, governed event" - both live in
config/platform.yaml's clustering section
(config/settings.py::ClusteringConfig), not as module constants here.

Type compatibility: the spec's own TYPE_COMPATIBILITY.get(pair, 0.0)
would score two same-typed attributes 0.0 whenever the exact pair isn't
one of the handful the table happens to enumerate (only ("string",
"string") is explicitly 1.0) - almost certainly a pseudocode gap, not
intent ("deliberately not equality" is framed around the *divergent*
pairs the table lists, not a claim that equality itself needs enumerating
attribute by attribute). Same data type therefore always resolves to 1.0
before the configured table is even consulted - a documented, deliberate
correction, the same class of fix as Increment 6's Budget.stage_spend.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from config.settings import ClusteringConfig
from generated.C5.AttributeRecord._1_0 import Constraint, Kind

from algorithms.profiling import ProfiledAttribute
from substrate.embedding import mock_embed
from substrate.ingest import attribute_embedding_text


def _default_embed(text: str, dimensions: int) -> list[float]:
    return mock_embed(text, dimensions=dimensions)


def compute_embeddings(
    attrs: Sequence[ProfiledAttribute],
    *,
    dimensions: int,
    embed_fn: Callable[[str, int], list[float]] = _default_embed,
) -> dict[str, list[float]]:
    """One embedding per attribute, keyed by attributeId - recomputed
    locally via the same deterministic embed_fn + text basis
    substrate/ingest.py used when the vector was first stored, so
    algorithms/ never needs its own DB connection just to score
    similarity. Injectable per this repo's established DI convention
    (gate/gate.py, substrate/ingest.py, agents/model_gateway.py)."""
    return {a.record.attributeId: embed_fn(attribute_embedding_text(a.record), dimensions) for a in attrs}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot: float = sum(x * y for x, y in zip(a, b))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def path_similarity(a_path: str | None, b_path: str | None) -> float:
    if a_path is None or b_path is None:
        return 0.0
    return jaccard(set(a_path.split(".")), set(b_path.split(".")))


def type_compatibility(config: ClusteringConfig, a_type: str, b_type: str) -> float:
    if a_type == b_type:
        return 1.0
    key = frozenset((a_type, b_type))
    for entry in config.type_compatibility:
        if frozenset((entry.a, entry.b)) == key:
            return entry.score
    return 0.0


_BOUND_RE = re.compile(r"^(minimum|maximum|minLength|maxLength)=(-?\d+(?:\.\d+)?)$")


def _numeric_bounds(
    constraints: Sequence[Constraint], kind: Kind, low_key: str, high_key: str
) -> tuple[float | None, float | None]:
    lo: float | None = None
    hi: float | None = None
    for c in constraints:
        if c.kind != kind:
            continue
        m = _BOUND_RE.match(c.expression)
        if not m:
            continue
        value = float(m.group(2))
        if m.group(1) == low_key:
            lo = value
        elif m.group(1) == high_key:
            hi = value
    return lo, hi


def _interval_overlap(
    a: tuple[float | None, float | None], b: tuple[float | None, float | None]
) -> float | None:
    """None if one side declares no bound at all for this kind (nothing
    to compare); otherwise the intersection/union ratio of the two
    (possibly one-sided) intervals."""
    a_lo, a_hi = a
    b_lo, b_hi = b
    if a_lo is None and a_hi is None:
        return None
    if b_lo is None and b_hi is None:
        return None
    lo_a = a_lo if a_lo is not None else float("-inf")
    hi_a = a_hi if a_hi is not None else float("inf")
    lo_b = b_lo if b_lo is not None else float("-inf")
    hi_b = b_hi if b_hi is not None else float("inf")
    intersection = max(0.0, min(hi_a, hi_b) - max(lo_a, lo_b))
    union = max(hi_a, hi_b) - min(lo_a, lo_b)
    if union == 0.0:
        return 1.0
    if union == float("inf"):
        # Two intervals that are BOTH unbounded on the same side (e.g.
        # "minimum=0" on both) have an infinite intersection too, and are
        # genuinely identical open-ended constraints - 1.0, not 0.0. A
        # finite intersection within an infinite union (one side bounded,
        # the other not) really is negligible overlap - 0.0.
        return 1.0 if intersection == float("inf") else 0.0
    return intersection / union


def pattern_range_similarity(a_constraints: Sequence[Constraint], b_constraints: Sequence[Constraint]) -> float:
    """Provisional constraint-overlap heuristic for attributes without a
    shared enumeration (constraint_overlap() below falls back to this).
    Neither side declares constraints -> neutral 0.5 (no evidence either
    way, not proof of a mismatch). Only one side does -> 0.3 (some
    evidence of divergence, not conclusive). Both sides do -> the mean
    per-shared-kind similarity (range/length: interval overlap ratio;
    pattern/format/crossField/custom: exact expression equality), or 0.0
    if the two sides share no constraint kind at all."""
    if not a_constraints and not b_constraints:
        return 0.5
    if not a_constraints or not b_constraints:
        return 0.3

    a_kinds = {c.kind for c in a_constraints}
    b_kinds = {c.kind for c in b_constraints}
    shared = a_kinds & b_kinds
    if not shared:
        return 0.0

    scores: list[float] = []
    for kind in shared:
        if kind == Kind.range:
            overlap = _interval_overlap(
                _numeric_bounds(a_constraints, kind, "minimum", "maximum"),
                _numeric_bounds(b_constraints, kind, "minimum", "maximum"),
            )
        elif kind == Kind.length:
            overlap = _interval_overlap(
                _numeric_bounds(a_constraints, kind, "minLength", "maxLength"),
                _numeric_bounds(b_constraints, kind, "minLength", "maxLength"),
            )
        else:
            a_exprs = {c.expression for c in a_constraints if c.kind == kind}
            b_exprs = {c.expression for c in b_constraints if c.kind == kind}
            overlap = 1.0 if a_exprs == b_exprs else 0.0
        if overlap is not None:
            scores.append(overlap)
    return sum(scores) / len(scores) if scores else 0.0


def constraint_overlap(a: ProfiledAttribute, b: ProfiledAttribute) -> float:
    """"Enumerations dominate: two fields sharing a code list are almost
    always the same concept, and two with disjoint code lists almost
    never are." Falls back to pattern_range_similarity when either side
    has no declared enumeration."""
    a_enum = a.record.enumeration or []
    b_enum = b.record.enumeration or []
    if a_enum and b_enum:
        va = {e.value.upper() for e in a_enum}
        vb = {e.value.upper() for e in b_enum}
        return len(va & vb) / max(len(va | vb), 1)
    return pattern_range_similarity(a.record.constraints or [], b.record.constraints or [])


def similarity(
    a: ProfiledAttribute,
    b: ProfiledAttribute,
    *,
    embeddings: Mapping[str, Sequence[float]],
    config: ClusteringConfig,
) -> tuple[float, dict[str, float]]:
    """Section 9.3's similarity(), against this repo's real
    ProfiledAttribute/ClusteringConfig shapes. embeddings is an explicit
    dict[attributeId, vector] parameter (from compute_embeddings()) - a
    documented, deliberate deviation from the pseudocode's literal
    a.embedding/b.embedding attribute access, matching Increment 6's
    factory-for-signature-constraint precedent - ProfiledAttribute
    (Increment 3) carries no embedding field and isn't changed here."""
    features = {
        "lexical": jaccard(set(a.tokens), set(b.tokens)),
        "embedding": cosine(
            embeddings.get(a.record.attributeId, []), embeddings.get(b.record.attributeId, [])
        ),
        "type": type_compatibility(config, a.record.dataType.value, b.record.dataType.value),
        "constraints": constraint_overlap(a, b),
        "context": 0.5 * path_similarity(a.parent_path, b.parent_path)
        + 0.5 * jaccard(set(a.sibling_names), set(b.sibling_names)),
    }
    score = sum(config.weights.get(name, 0.0) * value for name, value in features.items())
    return score, features
