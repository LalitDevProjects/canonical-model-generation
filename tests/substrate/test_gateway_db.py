from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

from gate.evidence_store import EvidenceStore
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from substrate.ingest import ingest_artefacts
from tools.gateway import ToolGateway

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly
from helpers import make_artefact

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
DIMENSIONS = 8


def _seed_and_gateway(tmp_path: Path, db: SubstrateDb) -> tuple[ToolGateway, str]:
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    run_store = RunStore(base_path=tmp_path / "run-store")
    content = GOLDEN_OPENAPI.read_bytes()
    artefact = make_artefact(artefact_id="art-openapi", region="uk", content=content, media_type="application/yaml")
    evidence_store.write_artefact(artefact.contentHash, content)

    manifest = C4Corpusmanifest.model_validate({
        "runId": str(uuid4()), "domain": "claims", "sealedAt": "2026-08-31T12:00:00Z",
        "corpusHash": "a" * 64, "artefacts": [artefact.model_dump(mode="json")], "exclusions": [],
    })
    ingest_artefacts(manifest.runId, manifest, evidence_store=evidence_store, run_store=run_store, db=db, dimensions=DIMENSIONS)

    substrate = SubstrateApi(db, run_store, dimensions=DIMENSIONS, acord_ingestion_enabled=False)
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=manifest.runId, substrate_api=substrate)
    return gateway, str(manifest.runId)


class TestSubstrateQueryHandler:
    def test_returns_real_chunks_via_the_gateway(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        gateway, run_id = _seed_and_gateway(tmp_path, substrate_db)
        result = gateway.call("repository-scout", "substrate.query", {"query": "claim identifier"}, uuid4())
        assert isinstance(result, list)
        assert len(result) > 0
        assert "evref" in result[0]


class TestSubstrateNeighboursHandler:
    def test_returns_real_neighbours_via_the_gateway(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        gateway, run_id = _seed_and_gateway(tmp_path, substrate_db)
        run_store = gateway.run_store
        [attribute] = run_store.read_attributes(UUID(run_id))[:1]
        result = gateway.call("schema-interpreter", "substrate.neighbours", {"attributeId": attribute.attributeId}, uuid4())
        assert isinstance(result, list)


class TestAcordLookupHandler:
    def test_always_returns_an_empty_list_via_the_gateway(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        gateway, run_id = _seed_and_gateway(tmp_path, substrate_db)
        result = gateway.call("acord-aligner", "acord.lookup", {"query": "ClaimNumber"}, uuid4())
        assert result == []
