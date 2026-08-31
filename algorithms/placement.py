"""
Core versus extension partitioning (Section 9.7 - "Core Algorithms").
place() is deterministic - "the agent writes the rationale; this
function decides." Called from within Canonical Synthesiser's own flow
(agents/canonical_synthesiser.py): the model is never trusted to invent
the placement itself (its guardrail G3: "placement MUST be produced by
the deterministic rules in 9.7").

ctx.absence_is_gap/.intends_to_close/.workshop_approved "read recorded
workshop decisions; they never guess" - no workshop-decision-recording
mechanism exists in this repo yet (no checkpoint/ratification UI - out
of scope, matching Increment 6/7's own orchestrator-deferral precedent),
so all three default to False via injectable callables: the safe,
conservative reading when nothing has been recorded. is_jurisdictional_
regulatory defaults to False for the same reason - "jurisdiction-specific
regulatory" has no corresponding classification field anywhere in
C5.AttributeRecord (obligation.level is mandatory/conditional/optional,
not a regulatory-vs-business distinction), so it genuinely cannot be
computed from data alone either; treated with the same "never guess"
discipline as the three the spec explicitly names. max_evidence_tier
IS real - it reads C5.AttributeRecord.evidenceTier directly via
SubstrateApi, no guessing required.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.common.defs import Level

from substrate.api import SubstrateApi

ALL_REGIONS = frozenset({"us", "uk", "eu"})

PlacementKind = Literal["core", "extension"]


@dataclass(frozen=True)
class Placement:
    kind: PlacementKind
    rule: str
    region: str | tuple[str, ...] | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlacementContext:
    max_evidence_tier: Callable[[C6Conceptcluster], int]
    is_jurisdictional_regulatory: Callable[[C6Conceptcluster], bool] = lambda cluster: False
    absence_is_gap: Callable[[C6Conceptcluster, frozenset[str]], bool] = lambda cluster, missing: False
    intends_to_close: Callable[[C6Conceptcluster], bool] = lambda cluster: False
    workshop_approved: Callable[[C6Conceptcluster], bool] = lambda cluster: False


def default_placement_context(substrate: SubstrateApi, run_id: str) -> PlacementContext:
    """Wires the one genuinely-computable callable (max_evidence_tier)
    against real data; the other four stay at their conservative False
    defaults unless a caller overrides them explicitly (golden fixtures
    proving rules 2/3's "true" branches do exactly this)."""

    def max_evidence_tier(cluster: C6Conceptcluster) -> int:
        tiers = [
            substrate.get_attribute(run_id, str(member.attributeId)).evidenceTier
            for member in cluster.members
        ]
        return max(tiers, default=1)

    return PlacementContext(max_evidence_tier=max_evidence_tier)


def sole_region(cluster: C6Conceptcluster) -> str:
    """Referenced but never defined in Section 9.7's own pseudocode - the
    single region a rule-3/4/5 extension is filed under. When a cluster
    genuinely spans one region, that's unambiguous. When it spans more
    (rules 4/5 don't gate on region count before firing), the
    alphabetically-first region is used as a deterministic, documented
    tie-break - a provisional reading, the same class of gap as
    algorithms/blocking.py's own lemmatise()/dedupe_blocks()."""
    regions = sorted({member.region.value for member in cluster.members})
    return regions[0] if regions else "us"


def place(cluster: C6Conceptcluster, ctx: PlacementContext) -> Placement:
    """Section 9.7's place(), verbatim. Rule numbers correspond to the
    design rules quoted in the workshop pack."""
    regions = {member.region.value for member in cluster.members}

    # Rule 4 - jurisdiction-specific regulatory obligation is ALWAYS an
    # extension, even where every region happens to have an equivalent:
    # the obligations differ.
    if ctx.is_jurisdictional_regulatory(cluster):
        return Placement("extension", region=sole_region(cluster), rule="4")

    # Rule 5 - vendor-only evidence never reaches core without workshop challenge
    if ctx.max_evidence_tier(cluster) == 3 and not ctx.workshop_approved(cluster):
        return Placement("extension", region=sole_region(cluster), rule="5", flags=("vendorOnly",))

    if len(regions) == 3:
        return Placement("core", rule="1")  # Rule 1

    if len(regions) == 2:
        missing = ALL_REGIONS - regions
        # Rule 2 - absence is a gap only if the workshop says it is not deliberate
        if ctx.absence_is_gap(cluster, frozenset(missing)):
            return Placement("core", rule="2", flags=(f"gap-in:{', '.join(sorted(missing))}",))
        return Placement("extension", region=tuple(sorted(regions)), rule="2")

    # Rule 3 - single region defaults to extension unless the syndicate
    # intends to close the omission elsewhere
    if ctx.intends_to_close(cluster):
        return Placement("core", rule="3", flags=("planned-adoption",))
    return Placement("extension", region=sole_region(cluster), rule="3")


def placement_to_contract_value(placement: Placement) -> str:
    """Maps a Placement onto C8.CanonicalCandidate's own placement enum
    (["core", "extension:us", "extension:uk", "extension:eu"]) - a single
    region per extension value. Rule 2's own extension branch can name
    TWO present regions (Placement.region is then a tuple) - the schema
    (an Increment 1 design call, not spec-mandated) has no room for a
    compound value, so the alphabetically-first region is used, the same
    deterministic tie-break as sole_region()."""
    if placement.kind == "core":
        return "core"
    if isinstance(placement.region, tuple):
        region = placement.region[0] if placement.region else "us"
    else:
        region = placement.region or "us"
    return f"extension:{region}"
