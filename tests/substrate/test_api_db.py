from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

from gate.evidence_store import EvidenceStore
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from substrate.ingest import ingest_artefacts

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly
from helpers import make_artefact

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
GOLDEN_XSD = REPO_ROOT / "golden" / "xsd" / "uk" / "ClaimNotification.xsd"

DIMENSIONS = 8


def _seed(tmp_path: Path, substrate_db: SubstrateDb) -> tuple[SubstrateApi, RunStore, str]:
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    run_store = RunStore(base_path=tmp_path / "run-store")

    fixtures = [
        ("art-openapi", GOLDEN_OPENAPI.read_bytes(), "application/yaml", "uk"),
        ("art-xsd", GOLDEN_XSD.read_bytes(), "application/xml", "uk"),
    ]
    artefacts: list[C1Sourceartefact] = []
    for artefact_id, content, media_type, region in fixtures:
        artefact = make_artefact(artefact_id=artefact_id, region=region, content=content, media_type=media_type)
        evidence_store.write_artefact(artefact.contentHash, content)
        artefacts.append(artefact)

    manifest = C4Corpusmanifest.model_validate({
        "runId": str(uuid4()),
        "domain": "claims",
        "sealedAt": "2026-08-31T12:00:00Z",
        "corpusHash": "a" * 64,
        "artefacts": [a.model_dump(mode="json") for a in artefacts],
        "exclusions": [],
    })
    ingest_artefacts(
        manifest.runId, manifest,
        evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
    )
    api = SubstrateApi(substrate_db, run_store, dimensions=DIMENSIONS, acord_ingestion_enabled=False)
    return api, run_store, str(manifest.runId)


class TestSearch:
    def test_returns_real_chunks_for_a_matching_query(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        results = api.search(run_id, "claim notification")
        assert len(results) > 0
        assert all(isinstance(r.score, float) for r in results)

    def test_deterministic_across_repeated_calls(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        first = [c.chunk_hash for c in api.search(run_id, "claim notification date")]
        second = [c.chunk_hash for c in api.search(run_id, "claim notification date")]
        assert first == second
        assert len(first) > 0

    def test_region_filter_narrows_results(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        results = api.search(run_id, "claim", region="uk")
        assert all(r.region == "uk" for r in results)

    def test_artefact_kinds_filter_narrows_results(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        results = api.search(run_id, "claim", artefact_kinds=["openapi"])
        assert len(results) > 0
        assert all(r.artefact_id == "art-openapi" for r in results)

    def test_a_different_run_id_sees_nothing(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, _ = _seed(tmp_path, substrate_db)
        assert api.search(str(uuid4()), "claim") == []

    def test_top_k_caps_the_result_count(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        results = api.search(run_id, "claim notification date policyholder broker", top_k=1)
        assert len(results) <= 1


class TestGetAttribute:
    def test_returns_the_matching_record(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, run_store, run_id = _seed(tmp_path, substrate_db)
        records = run_store.read_attributes(UUID(run_id))
        assert records
        found = api.get_attribute(run_id, records[0].attributeId)
        assert found.attributeId == records[0].attributeId

    def test_raises_key_error_for_an_unknown_attribute(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        with pytest.raises(KeyError):
            api.get_attribute(run_id, "attr://uk/does-not-exist/x")


class TestNeighbours:
    def test_unknown_attribute_returns_an_empty_list(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        assert api.neighbours(run_id, "attr://uk/does-not-exist/x") == []

    def test_known_attribute_returns_other_attributes_never_itself(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, run_store, run_id = _seed(tmp_path, substrate_db)
        records = run_store.read_attributes(UUID(run_id))
        assert len(records) > 1
        seed_id = records[0].attributeId
        results = api.neighbours(run_id, seed_id, top_k=len(records))
        assert seed_id not in {r.attributeId for r in results}
        assert len(results) == len(records) - 1


class TestAcordLookup:
    def test_always_returns_an_empty_list(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, run_id = _seed(tmp_path, substrate_db)
        assert api.acord_lookup(run_id, "ClaimNumber") == []

    def test_every_call_is_journalled(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, run_store, run_id = _seed(tmp_path, substrate_db)
        run_uuid = UUID(run_id)
        before = run_store.next_journal_seq(run_uuid)
        api.acord_lookup(run_id, "ClaimNumber")
        api.acord_lookup(run_id, "ClaimNumber")
        after = run_store.next_journal_seq(run_uuid)
        assert after == before + 2


class TestLineage:
    def test_delegates_to_the_graph_lineage_query(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, run_store, run_id = _seed(tmp_path, substrate_db)
        [attribute] = run_store.read_attributes(UUID(run_id))[:1]
        result = api.lineage(attribute.attributeId)
        node_types = {n.node_type for n in result.nodes}
        assert "Attribute" in node_types
        assert "Artefact" in node_types

    def test_unknown_seed_returns_an_empty_graph(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        api, _, _ = _seed(tmp_path, substrate_db)
        result = api.lineage("canon://does-not-exist")
        assert result.nodes == []
        assert result.edges == []
