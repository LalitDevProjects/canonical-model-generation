"""pytest.mark.db companion to tests/algorithms/test_blocking.py's
hermetic tests: proves build_blocks' third key (by_embedding, DB-backed
via SubstrateApi.neighbours) for real, against a live Postgres. The
hermetic acceptance test (tests/algorithms/test_clustering_acceptance.py)
runs with api=None and never exercises this path."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.blocking import build_blocks
from algorithms.profiling import profile
from config.settings import ClusteringConfig
from gate.evidence_store import EvidenceStore
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from substrate.ingest import ingest_artefacts

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly
from helpers import make_artefact

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_UK_CLAIM = REPO_ROOT / "golden" / "clustering" / "uk" / "claim.yaml"

DIMENSIONS = 8


def _seed(tmp_path: Path, substrate_db: SubstrateDb) -> tuple[RunStore, str]:
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    run_store = RunStore(base_path=tmp_path / "run-store")

    content = GOLDEN_UK_CLAIM.read_bytes()
    artefact: C1Sourceartefact = make_artefact(
        artefact_id="claims-clustering-uk", region="uk", content=content, media_type="application/vnd.oai.openapi"
    )
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
    return run_store, str(manifest.runId)


class TestBuildBlocksEmbeddingKey:
    def test_embedding_key_contributes_a_real_block(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        run_store, run_id = _seed(tmp_path, substrate_db)
        api = SubstrateApi(substrate_db, run_store, dimensions=DIMENSIONS, acord_ingestion_enabled=False)

        records = run_store.read_attributes(UUID(run_id))
        by_parent: dict[str | None, list[C5Attributerecord]] = {}
        for r in records:
            by_parent.setdefault(r.parentPath, []).append(r)
        profiled = [
            profile(r, siblings=[s for s in by_parent[r.parentPath] if s.attributeId != r.attributeId])
            for r in records
        ]

        config = ClusteringConfig(block_top_k=25)
        blocks_without_api = build_blocks(profiled, config=config)
        blocks_with_api = build_blocks(profiled, run_id=run_id, api=api, config=config)

        embedding_blocks = [b for b in blocks_with_api if b.anchor is not None]
        assert len(embedding_blocks) > 0
        assert len(blocks_with_api) >= len(blocks_without_api)
