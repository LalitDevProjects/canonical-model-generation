"""
Conflict classification (Section 9.5 - "Core Algorithms"). Homonym
splitting (HOMONYM_SIGNALS/split_on_homonym_signals/min_cut_until) plus
the remaining four §9.5 taxonomy rows (granularity/type/enumeration/
obligation) via classify_conflict(), for clusters that survive homonym
splitting intact.

"A single [homonym] signal is sufficient - this is intentionally
trigger-happy."

contradiction_detected (the "documentation-contradiction" signal) is an
honest, permanent stub: the spec ties it to "critic-assessed, cached" -
the Adversarial Critic agent (Section 7.5.4) doesn't exist until
Increment 8/9. Not a fake heuristic standing in for a not-yet-built
agent, matching substrate/api.py::acord_lookup's own empty-list
precedent for the same class of honest gap.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from config.settings import ClusteringConfig
from generated.common.defs import DataType, Level

from algorithms.graph import connected_components
from algorithms.profiling import ProfiledAttribute
from algorithms.similarity import path_similarity, type_compatibility


def pairwise_type_compat(members: Sequence[ProfiledAttribute], config: ClusteringConfig) -> list[float]:
    return [
        type_compatibility(config, a.record.dataType.value, b.record.dataType.value)
        for a, b in combinations(members, 2)
    ]


def _enum_values(member: ProfiledAttribute) -> set[str] | None:
    if not member.record.enumeration:
        return None
    return {item.value.upper() for item in member.record.enumeration}


def all_have_enums(members: Sequence[ProfiledAttribute]) -> bool:
    return all(_enum_values(m) is not None for m in members)


def enum_overlap(members: Sequence[ProfiledAttribute]) -> float:
    """Global intersection-over-union across every member's enumeration
    (not a pairwise average) - a single, unambiguous "how much of the
    combined vocabulary do all members agree on" score. union is
    guaranteed non-empty here: _enum_values already filters out members
    with no enumeration at all, so every remaining value_sets entry has
    >=1 element."""
    value_sets = [v for m in members if (v := _enum_values(m)) is not None]
    if len(value_sets) < 2:
        return 1.0
    union = set().union(*value_sets)
    intersection = set.intersection(*value_sets)
    return len(intersection) / len(union)


def has_mandatory(members: Sequence[ProfiledAttribute]) -> bool:
    return any(m.record.obligation.level == Level.mandatory for m in members)


def has_absent_in_sibling_region(members: Sequence[ProfiledAttribute]) -> bool:
    """Provisional reading of "absent in a sibling region": some member
    is mandatory while another member, from a different region, is not
    (optional/conditional) - the closest code-checkable proxy available
    without a full per-region attribute-presence index (which no part of
    this codebase maintains). Documented as a deliberate simplification,
    not a literal absence check."""
    mandatory_regions = {m.record.region for m in members if m.record.obligation.level == Level.mandatory}
    non_mandatory_regions = {m.record.region for m in members if m.record.obligation.level != Level.mandatory}
    return bool(mandatory_regions and non_mandatory_regions)


def contradiction_detected(members: Sequence[ProfiledAttribute]) -> bool:
    """Permanent stub - see module docstring. Always False until the
    Adversarial Critic agent exists to assess it for real."""
    return False


def max_pairwise_path_distance(members: Sequence[ProfiledAttribute]) -> float:
    """Pairs where either member has no recorded parentPath contribute no
    evidence of divergence (path_similarity's own None handling treats
    missing context as dissimilar for *scoring* purposes, which would
    otherwise make this signal fire on every pair of attributes that
    simply lack parent-path data - the opposite of what "divergent"
    should mean)."""
    distances = [
        1.0 - path_similarity(a.parent_path, b.parent_path)
        for a, b in combinations(members, 2)
        if a.parent_path is not None and b.parent_path is not None
    ]
    return max(distances) if distances else 0.0


_SignalTest = Callable[[Sequence[ProfiledAttribute], ClusteringConfig], bool]

HOMONYM_SIGNALS: list[tuple[str, _SignalTest]] = [
    ("type-incompatible", lambda ms, cfg: bool(pairwise_type_compat(ms, cfg)) and min(pairwise_type_compat(ms, cfg)) < 0.35),
    ("disjoint-enumerations", lambda ms, cfg: all_have_enums(ms) and enum_overlap(ms) == 0.0),
    ("obligation-inversion", lambda ms, cfg: has_mandatory(ms) and has_absent_in_sibling_region(ms)),
    ("documentation-contradiction", lambda ms, cfg: contradiction_detected(ms)),
    ("divergent-parent-context", lambda ms, cfg: max_pairwise_path_distance(ms) > 0.8),
]


@dataclass(frozen=True)
class MemberGroup:
    members: tuple[ProfiledAttribute, ...]
    conflict_class: str | None
    conflict_detail: str | None


def _any_signal_fires(members: Sequence[ProfiledAttribute], config: ClusteringConfig) -> bool:
    return any(test(members, config) for _, test in HOMONYM_SIGNALS)


def min_cut_until(
    members: Sequence[ProfiledAttribute],
    edges: Mapping[frozenset[str], float],
    config: ClusteringConfig,
) -> list[list[ProfiledAttribute]]:
    """Greedy edge-removal, NOT Stoer-Wagner min-cut - sufficient at PoC
    block sizes (<=40 members, Section 8.6). Repeatedly drops the group's
    own lowest-scoring internal edge and recomputes connected components
    until no HOMONYM_SIGNALS test fires within any resulting sub-group."""
    members = list(members)
    if len(members) < 2 or not _any_signal_fires(members, config):
        return [members]

    ids = [m.record.attributeId for m in members]
    id_set = frozenset(ids)
    internal_edges = {pair: score for pair, score in edges.items() if pair <= id_set}
    if not internal_edges:
        # No edge left to remove but a signal still fires: the group
        # can't be graph-partitioned further, so every member becomes
        # its own singleton (no signal can fire on a lone member, so
        # this always terminates).
        return [[m] for m in members]

    worst_pair = min(internal_edges, key=lambda pair: internal_edges[pair])
    remaining_edges = {pair: score for pair, score in internal_edges.items() if pair != worst_pair}

    by_id = {m.record.attributeId: m for m in members}
    result: list[list[ProfiledAttribute]] = []
    for component_ids in connected_components(ids, remaining_edges):
        sub_members = [by_id[i] for i in component_ids]
        result.extend(min_cut_until(sub_members, remaining_edges, config))
    return result


def split_on_homonym_signals(
    members: Sequence[ProfiledAttribute],
    edges: Mapping[frozenset[str], float],
    config: ClusteringConfig,
) -> list[MemberGroup]:
    """Section 9.5's split_on_homonym_signals(). Returns MemberGroup
    objects (conflictClass/conflictDetail attached per group) rather than
    mutating the input the way the pseudocode's `grp.conflict_class = ...`
    does - ProfiledAttribute is a frozen dataclass, and a plain list has
    nowhere to hang that state."""
    members = list(members)
    fired = [name for name, test in HOMONYM_SIGNALS if test(members, config)]
    if not fired:
        return [MemberGroup(members=tuple(members), conflict_class=None, conflict_detail=None)]

    detail = "split on: " + ", ".join(fired)
    groups = min_cut_until(members, edges, config)
    return [MemberGroup(members=tuple(g), conflict_class="homonym", conflict_detail=detail) for g in groups]


def _has_obligation_conflict(members: Sequence[ProfiledAttribute]) -> bool:
    return len({m.record.obligation.level for m in members}) > 1


def _has_granularity_conflict(members: Sequence[ProfiledAttribute]) -> bool:
    structural_heads = {m.head_noun for m in members if m.record.dataType in (DataType.object, DataType.array)}
    scalar_heads = {m.head_noun for m in members if m.record.dataType not in (DataType.object, DataType.array)}
    return bool(structural_heads & scalar_heads)


def _type_conflict_detail(members: Sequence[ProfiledAttribute], config: ClusteringConfig) -> str | None:
    scores = pairwise_type_compat(members, config)
    if scores and min(scores) < 1.0:
        return f"weakest pairwise type compatibility {min(scores):.2f}"
    return None


def _enumeration_conflict_detail(members: Sequence[ProfiledAttribute]) -> str | None:
    if not all_have_enums(members):
        return None
    overlap = enum_overlap(members)
    if 0.0 < overlap < 1.0:
        return f"enumeration overlap {overlap:.2f}"
    return None


def classify_conflict(members: Sequence[ProfiledAttribute], config: ClusteringConfig) -> tuple[str | None, str | None]:
    """Dispatches the remaining four Section 9.5 conflict classes
    (granularity/type/enumeration/obligation) for a group that has
    already survived split_on_homonym_signals intact. Checked in order
    obligation -> granularity -> type -> enumeration -> clean synonym:
    obligation first because it is the taxonomy's own strongest-
    consequence row ("Never resolved by an agent"); only the first
    applicable class is returned, matching the taxonomy's framing of six
    mutually exclusive descriptions for one merge decision."""
    if len(members) < 2:
        return None, None
    if _has_obligation_conflict(members):
        return "obligation", "obligation levels differ across members"
    if _has_granularity_conflict(members):
        return "granularity", "a structural member (object/array) shares a head noun with a scalar sibling"
    type_detail = _type_conflict_detail(members, config)
    if type_detail is not None:
        return "type", type_detail
    enum_detail = _enumeration_conflict_detail(members)
    if enum_detail is not None:
        return "enumeration", enum_detail
    return None, None
