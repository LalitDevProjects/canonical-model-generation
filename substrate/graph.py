"""
The concept graph (Section 6.3) - node/edge writes and the lineage query
that justifies the whole graph existing: "Which regional artefacts, at
which versions, support canonical attribute X in release 1.0, and who
ratified it? is a four-hop traversal, answerable in milliseconds, years
later."

A generic property graph (substrate/schema.sql's nodes/edges tables), not
one physical table per node/edge type - see substrate/schema.sql's own
docstring for the full reasoning (a single recursive CTE over
heterogeneously-typed hops, versus a 7x7 UNION ALL).

node_id is always the real contract's own id
(artefactId/attributeId/clusterId/candidateId for
Artefact/Attribute/Cluster/Candidate - never a parallel identifier).
AcordConcept/Release/Decision have no C-numbered contract anywhere
(Section 6.3 introduces them fresh; contracts/ stops at C11) - their
properties are plain frozen dataclasses here, the same status as
algorithms/profiling.py's Finding/ProfiledAttribute (transient,
non-contract shapes), not new JSON-Schema contracts.

Writes are idempotent upserts: Section 6's own framing is that this data
is "derived; may be dropped and reconstructed from the evidence store."
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import psycopg

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

NODE_TYPES = frozenset({
    "Artefact", "Attribute", "Cluster", "AcordConcept", "Candidate", "Release", "Decision",
})
EDGE_TYPES = frozenset({
    "EVIDENCED_BY", "MEMBER_OF", "ALIGNS_TO", "PRODUCED", "RATIFIED_BY", "RELEASED_IN", "SUPERSEDES",
})


@dataclass(frozen=True)
class AcordConceptProps:
    """Section 6.3: AcordConcept(acordRef, model, entity, attribute).
    Always synthetic in this repo - ACORD Reference Architecture data is
    unlicensed/unavailable (a locked-in decision from Increment 1)."""

    acord_ref: str
    model: str
    entity: str
    attribute: str


@dataclass(frozen=True)
class ReleaseProps:
    """Section 6.3: Release(domain, semver, signedAt)."""

    domain: str
    semver: str
    signed_at: str


@dataclass(frozen=True)
class DecisionProps:
    """Section 6.3: Decision(decisionId, kind, sme, decidedAt)."""

    decision_id: str
    kind: str
    sme: str
    decided_at: str


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str
    properties: dict[str, object]


@dataclass(frozen=True)
class GraphEdge:
    from_id: str
    to_id: str
    edge_type: str
    properties: dict[str, object]


@dataclass(frozen=True)
class LineageGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def write_node(
    conn: psycopg.Connection,
    node_id: str,
    node_type: str,
    properties: dict[str, object],
    *,
    run_id: str | None = None,
) -> None:
    if node_type not in NODE_TYPES:
        raise ValueError(f"unknown node_type {node_type!r}; must be one of {sorted(NODE_TYPES)}")
    conn.execute(
        """
        INSERT INTO nodes (node_id, node_type, run_id, properties)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (node_id) DO UPDATE SET
            node_type = EXCLUDED.node_type,
            run_id = EXCLUDED.run_id,
            properties = EXCLUDED.properties,
            updated_at = now()
        """,
        (node_id, node_type, run_id, json.dumps(properties, sort_keys=True)),
    )


def write_edge(
    conn: psycopg.Connection,
    from_id: str,
    to_id: str,
    edge_type: str,
    properties: dict[str, object] | None = None,
) -> None:
    if edge_type not in EDGE_TYPES:
        raise ValueError(f"unknown edge_type {edge_type!r}; must be one of {sorted(EDGE_TYPES)}")
    conn.execute(
        """
        INSERT INTO edges (from_id, to_id, edge_type, properties)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (from_id, to_id, edge_type) DO UPDATE SET properties = EXCLUDED.properties
        """,
        (from_id, to_id, edge_type, json.dumps(properties or {}, sort_keys=True)),
    )


def node_from_artefact(artefact: C1Sourceartefact) -> tuple[str, str, dict[str, object]]:
    return (
        artefact.artefactId,
        "Artefact",
        {
            "artefactId": artefact.artefactId,
            "region": artefact.region.value,
            "system": artefact.system.value,
            "tier": artefact.evidenceTier,
            "contentHash": artefact.contentHash,
        },
    )


def node_from_attribute(record: C5Attributerecord) -> tuple[str, str, dict[str, object]]:
    return (
        record.attributeId,
        "Attribute",
        {
            "attributeId": record.attributeId,
            "region": record.region.value,
            "path": record.path,
            "dataType": record.dataType.value,
            "obligation": record.obligation.level.value,
        },
    )


def edge_attribute_evidenced_by(record: C5Attributerecord) -> tuple[str, str, str]:
    """Attribute -[:EVIDENCED_BY]-> Artefact. record.sourceContract is
    literally the source artefact's own artefactId (parsers/record_builder.py:
    "sourceContract=source_artefact.artefactId")."""
    return (record.attributeId, record.sourceContract, "EVIDENCED_BY")


def node_from_acord_concept(props: AcordConceptProps) -> tuple[str, str, dict[str, object]]:
    return (f"acord://{props.acord_ref}", "AcordConcept", asdict(props))


def node_from_release(props: ReleaseProps) -> tuple[str, str, dict[str, object]]:
    return (f"release://{props.domain}/{props.semver}", "Release", asdict(props))


def node_from_decision(props: DecisionProps) -> tuple[str, str, dict[str, object]]:
    return (f"decision://{props.decision_id}", "Decision", asdict(props))


_LINEAGE_NODE_IDS_SQL = """
WITH RECURSIVE lineage AS (
    SELECT node_id, 0 AS depth, ARRAY[node_id] AS path
    FROM nodes WHERE node_id = %(seed)s
    UNION ALL
    SELECT n.node_id, l.depth + 1, l.path || n.node_id
    FROM lineage l
    JOIN edges e ON e.from_id = l.node_id OR e.to_id = l.node_id
    JOIN nodes n ON n.node_id = CASE WHEN e.from_id = l.node_id THEN e.to_id ELSE e.from_id END
    WHERE NOT (n.node_id = ANY(l.path)) AND l.depth < %(max_depth)s
)
SELECT DISTINCT node_id FROM lineage
"""


def lineage(conn: psycopg.Connection, seed_node_id: str, *, max_depth: int = 6) -> LineageGraph:
    """Bidirectional recursive CTE: a PoC-scale graph doesn't need
    per-edge-type directionality encoded specially - "the traversals
    required are shallow" (Section 6.3), and walking every edge touching
    the current frontier (regardless of which side it's declared on) is
    what makes a single query answer the spec's own four-hop worked
    example without hand-coding which edge types point which way."""
    node_id_rows = conn.execute(
        _LINEAGE_NODE_IDS_SQL, {"seed": seed_node_id, "max_depth": max_depth}
    ).fetchall()
    node_ids = [row[0] for row in node_id_rows]
    if not node_ids:
        return LineageGraph(nodes=[], edges=[])

    node_rows = conn.execute(
        "SELECT node_id, node_type, properties FROM nodes WHERE node_id = ANY(%s) ORDER BY node_id",
        (node_ids,),
    ).fetchall()
    nodes = [GraphNode(node_id=row[0], node_type=row[1], properties=row[2]) for row in node_rows]

    edge_rows = conn.execute(
        """
        SELECT from_id, to_id, edge_type, properties FROM edges
        WHERE from_id = ANY(%(ids)s) AND to_id = ANY(%(ids)s)
        ORDER BY from_id, to_id, edge_type
        """,
        {"ids": node_ids},
    ).fetchall()
    edges = [
        GraphEdge(from_id=row[0], to_id=row[1], edge_type=row[2], properties=row[3])
        for row in edge_rows
    ]
    return LineageGraph(nodes=nodes, edges=edges)
