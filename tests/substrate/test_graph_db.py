from __future__ import annotations

import pytest

from substrate.db import SubstrateDb
from substrate.graph import (
    AcordConceptProps,
    DecisionProps,
    ReleaseProps,
    lineage,
    node_from_acord_concept,
    node_from_decision,
    node_from_release,
    write_edge,
    write_node,
)

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly

pytestmark = pytest.mark.db


def _seed_lineage_chain(db: SubstrateDb) -> None:
    """Attribute -[MEMBER_OF]-> Cluster -[PRODUCED]-> Candidate, plus
    Attribute -[EVIDENCED_BY]-> Artefact, Cluster -[ALIGNS_TO]->
    AcordConcept, Candidate -[RATIFIED_BY]-> Decision, Candidate
    -[RELEASED_IN]-> Release - every node/edge type Section 6.3 names,
    in one connected chain."""
    with db.connection() as conn:
        write_node(conn, "art-1", "Artefact", {"artefactId": "art-1"})
        write_node(conn, "attr://uk/art-1/claimId", "Attribute", {"attributeId": "attr://uk/art-1/claimId"})
        write_node(conn, "cluster://x", "Cluster", {"clusterId": "cluster://x"})
        write_node(conn, "canon://Claim.claimId", "Candidate", {"candidateId": "canon://Claim.claimId"})

        acord_id, acord_type, acord_props = node_from_acord_concept(
            AcordConceptProps(acord_ref="Claim.ClaimNumber", model="Claims", entity="Claim", attribute="ClaimNumber")
        )
        write_node(conn, acord_id, acord_type, acord_props)

        decision_id, decision_type, decision_props = node_from_decision(
            DecisionProps(decision_id="d1", kind="ratify", sme="jane.doe", decided_at="2026-08-31T12:00:00Z")
        )
        write_node(conn, decision_id, decision_type, decision_props)

        release_id, release_type, release_props = node_from_release(
            ReleaseProps(domain="claims", semver="1.0.0", signed_at="2026-08-31T12:00:00Z")
        )
        write_node(conn, release_id, release_type, release_props)

        write_edge(conn, "attr://uk/art-1/claimId", "art-1", "EVIDENCED_BY")
        write_edge(conn, "attr://uk/art-1/claimId", "cluster://x", "MEMBER_OF")
        write_edge(conn, "cluster://x", acord_id, "ALIGNS_TO", {"verdict": "fit"})
        write_edge(conn, "cluster://x", "canon://Claim.claimId", "PRODUCED")
        write_edge(conn, "canon://Claim.claimId", decision_id, "RATIFIED_BY")
        write_edge(conn, "canon://Claim.claimId", release_id, "RELEASED_IN")


class TestWriteNode:
    def test_rejects_an_unknown_node_type(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            with pytest.raises(ValueError):
                write_node(conn, "x", "NotARealType", {})

    def test_upsert_is_idempotent_and_updates_properties(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            write_node(conn, "art-1", "Artefact", {"tier": 1})
            write_node(conn, "art-1", "Artefact", {"tier": 2})
            row = conn.execute("SELECT properties FROM nodes WHERE node_id = %s", ("art-1",)).fetchone()
        assert row is not None
        assert row[0]["tier"] == 2


class TestWriteEdge:
    def test_rejects_an_unknown_edge_type(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            write_node(conn, "a", "Artefact", {})
            write_node(conn, "b", "Artefact", {})
            with pytest.raises(ValueError):
                write_edge(conn, "a", "b", "NOT_A_REAL_EDGE")

    def test_upsert_is_idempotent(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            write_node(conn, "a", "Artefact", {})
            write_node(conn, "b", "Artefact", {})
            write_edge(conn, "a", "b", "EVIDENCED_BY")
            write_edge(conn, "a", "b", "EVIDENCED_BY")
            rows = conn.execute("SELECT count(*) FROM edges WHERE from_id = %s AND to_id = %s", ("a", "b")).fetchall()
        assert rows[0][0] == 1


class TestLineage:
    def test_unknown_seed_returns_an_empty_graph(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            result = lineage(conn, "does-not-exist")
        assert result.nodes == []
        assert result.edges == []

    def test_seed_alone_is_included_even_with_no_edges(self, substrate_db: SubstrateDb) -> None:
        with substrate_db.connection() as conn:
            write_node(conn, "lonely", "Artefact", {})
            result = lineage(conn, "lonely")
        assert [n.node_id for n in result.nodes] == ["lonely"]

    def test_reaches_every_node_type_from_the_attribute_end_of_the_chain(self, substrate_db: SubstrateDb) -> None:
        _seed_lineage_chain(substrate_db)
        with substrate_db.connection() as conn:
            result = lineage(conn, "attr://uk/art-1/claimId", max_depth=6)
        node_types = {n.node_type for n in result.nodes}
        assert node_types == {"Artefact", "Attribute", "Cluster", "AcordConcept", "Candidate", "Decision", "Release"}

    def test_the_four_hop_worked_query_reaches_the_artefact_from_the_candidate(self, substrate_db: SubstrateDb) -> None:
        # "Which regional artefacts... support canonical attribute X in
        # release 1.0, and who ratified it?" (Section 6.3) - starting
        # from the Candidate, not the Attribute.
        _seed_lineage_chain(substrate_db)
        with substrate_db.connection() as conn:
            result = lineage(conn, "canon://Claim.claimId", max_depth=6)
        by_id = {n.node_id: n for n in result.nodes}
        assert "art-1" in by_id and by_id["art-1"].node_type == "Artefact"
        assert "decision://d1" in by_id and by_id["decision://d1"].node_type == "Decision"
        assert "release://claims/1.0.0" in by_id and by_id["release://claims/1.0.0"].node_type == "Release"

    def test_max_depth_limits_the_traversal(self, substrate_db: SubstrateDb) -> None:
        _seed_lineage_chain(substrate_db)
        with substrate_db.connection() as conn:
            shallow = lineage(conn, "canon://Claim.claimId", max_depth=1)
        node_ids = {n.node_id for n in shallow.nodes}
        # depth 1 from the Candidate reaches Cluster/Decision/Release directly...
        assert "cluster://x" in node_ids
        assert "decision://d1" in node_ids
        # ...but not the Attribute or Artefact, two and three hops away.
        assert "attr://uk/art-1/claimId" not in node_ids
        assert "art-1" not in node_ids

    def test_edges_returned_are_restricted_to_the_discovered_node_set(self, substrate_db: SubstrateDb) -> None:
        _seed_lineage_chain(substrate_db)
        with substrate_db.connection() as conn:
            write_node(conn, "unrelated-a", "Artefact", {})
            write_node(conn, "unrelated-b", "Artefact", {})
            write_edge(conn, "unrelated-a", "unrelated-b", "EVIDENCED_BY")
            result = lineage(conn, "canon://Claim.claimId", max_depth=6)
        edge_node_ids = {e.from_id for e in result.edges} | {e.to_id for e in result.edges}
        assert "unrelated-a" not in edge_node_ids
        assert "unrelated-b" not in edge_node_ids

    def test_aligns_to_edge_properties_carry_the_verdict(self, substrate_db: SubstrateDb) -> None:
        _seed_lineage_chain(substrate_db)
        with substrate_db.connection() as conn:
            result = lineage(conn, "cluster://x", max_depth=1)
        [aligns_to_edge] = [e for e in result.edges if e.edge_type == "ALIGNS_TO"]
        assert aligns_to_edge.properties == {"verdict": "fit"}
