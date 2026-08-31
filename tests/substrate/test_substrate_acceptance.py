"""
Increment 5's literal acceptance test (Section 17.2): "Retrieval is
deterministic across repeats; the four-hop lineage query returns the
expected path."
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

from gate.evidence_store import EvidenceStore
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from substrate.ingest import ingest_artefacts

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly
from fixtures import load_graph_fixture
from helpers import make_artefact

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
GOLDEN_XSD = REPO_ROOT / "golden" / "xsd" / "uk" / "ClaimNotification.xsd"
GOLDEN_GRAPH_FIXTURE = REPO_ROOT / "golden" / "substrate" / "graph_fixture.json"

DIMENSIONS = 8
XSD_ARTEFACT_ID = "claims-uk-notification"
"""Must match golden/substrate/graph_fixture.json's own hardcoded
seed_attribute_id, which is derived from this exact artefactId."""


class TestRetrievalIsDeterministicAcrossRepeats:
    def test_identical_search_calls_return_the_same_ordered_chunks(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
        run_store = RunStore(base_path=tmp_path / "run-store")

        content = GOLDEN_OPENAPI.read_bytes()
        artefact = make_artefact(artefact_id="art-openapi", region="uk", content=content, media_type="application/yaml")
        evidence_store.write_artefact(artefact.contentHash, content)

        manifest = C4Corpusmanifest.model_validate({
            "runId": str(uuid4()),
            "domain": "claims",
            "sealedAt": "2026-08-31T12:00:00Z",
            "corpusHash": "a" * 64,
            "artefacts": [artefact.model_dump(mode="json")],
            "exclusions": [],
        })
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )

        api = SubstrateApi(substrate_db, run_store, dimensions=DIMENSIONS, acord_ingestion_enabled=False)
        run_id = str(manifest.runId)

        first = api.search(run_id, "claim identifier")
        second = api.search(run_id, "claim identifier")

        assert len(first) > 0
        assert [c.chunk_hash for c in first] == [c.chunk_hash for c in second]
        assert [c.score for c in first] == [c.score for c in second]
        assert [c.text for c in first] == [c.text for c in second]


class TestFourHopLineageQueryReturnsTheExpectedPath:
    def test_lineage_from_the_candidate_reaches_every_expected_node(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        # "Which regional artefacts, at which versions, support canonical
        # attribute X in release 1.0, and who ratified it?" (Section
        # 6.3) - a real Attribute (parsed for real from the golden XSD
        # fixture) evidenced by a real Artefact, joined through a
        # hand-authored Cluster/AcordConcept/Candidate/Decision/Release
        # chain (golden/substrate/graph_fixture.json) via the exact same
        # write_node/write_edge functions production ingestion uses.
        evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
        run_store = RunStore(base_path=tmp_path / "run-store")

        content = GOLDEN_XSD.read_bytes()
        artefact = make_artefact(artefact_id=XSD_ARTEFACT_ID, region="uk", content=content, media_type="application/xml")
        evidence_store.write_artefact(artefact.contentHash, content)

        manifest = C4Corpusmanifest.model_validate({
            "runId": str(uuid4()),
            "domain": "claims",
            "sealedAt": "2026-08-31T12:00:00Z",
            "corpusHash": "a" * 64,
            "artefacts": [artefact.model_dump(mode="json")],
            "exclusions": [],
        })
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )

        with substrate_db.connection() as conn:
            fixture_payload = load_graph_fixture(conn, GOLDEN_GRAPH_FIXTURE)

        # The fixture's own claimed seed attribute must be the real one
        # ingestion actually produced - if this ever drifts (e.g. the
        # XSD parser's path-naming convention changes), this assertion
        # fails loudly instead of the lineage query silently finding
        # nothing.
        seed_attribute_id = fixture_payload["seed_attribute_id"]
        attributes = run_store.read_attributes(manifest.runId)
        assert any(a.attributeId == seed_attribute_id for a in attributes)

        api = SubstrateApi(substrate_db, run_store, dimensions=DIMENSIONS, acord_ingestion_enabled=False)
        result = api.lineage(fixture_payload["seed_candidate_id"])

        node_types_by_id = {n.node_id: n.node_type for n in result.nodes}
        assert node_types_by_id[fixture_payload["seed_candidate_id"]] == "Candidate"
        assert node_types_by_id[seed_attribute_id] == "Attribute"
        assert node_types_by_id[artefact.artefactId] == "Artefact"
        assert set(node_types_by_id.values()) == {
            "Candidate", "Cluster", "AcordConcept", "Decision", "Release", "Attribute", "Artefact",
        }

        edge_types = {e.edge_type for e in result.edges}
        assert edge_types == {
            "EVIDENCED_BY", "MEMBER_OF", "ALIGNS_TO", "PRODUCED", "RATIFIED_BY", "RELEASED_IN",
        }
