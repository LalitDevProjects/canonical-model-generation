from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

from gate.evidence_store import EvidenceStore
from pipeline.run_store import RunStore
from substrate.db import SubstrateDb
from substrate.ingest import ingest_artefacts

from db_fixture import substrate_db  # used as a pytest fixture below, not called directly
from helpers import make_artefact

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
GOLDEN_XSD = REPO_ROOT / "golden" / "xsd" / "uk" / "ClaimNotification.xsd"
GOLDEN_WSDL = REPO_ROOT / "golden" / "wsdl" / "uk" / "ClaimNotificationService.wsdl"
GOLDEN_AVRO = REPO_ROOT / "golden" / "avro" / "us" / "ClaimEvent.avsc"
GOLDEN_CONFLUENCE = REPO_ROOT / "golden" / "confluence" / "claims-uk-glossary.json"

DIMENSIONS = 8


def _seed_manifest_and_evidence(tmp_path: Path) -> tuple[C4Corpusmanifest, EvidenceStore, RunStore]:
    evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")
    run_store = RunStore(base_path=tmp_path / "run-store")

    confluence_page = json.loads(GOLDEN_CONFLUENCE.read_bytes())
    confluence_content = confluence_page["body"]["storage"]["value"].encode("utf-8")

    fixtures: list[tuple[str, bytes, str, str, str]] = [
        # (artefact_id, content, media_type, region, system)
        ("art-openapi", GOLDEN_OPENAPI.read_bytes(), "application/yaml", "uk", "git"),
        ("art-xsd", GOLDEN_XSD.read_bytes(), "application/xml", "uk", "git"),
        ("art-wsdl", GOLDEN_WSDL.read_bytes(), "application/xml", "uk", "git"),
        ("art-avro", GOLDEN_AVRO.read_bytes(), "application/vnd.apache.avro+json", "us", "git"),
        ("art-confluence", confluence_content, "application/vnd.atlassian.confluence.storage+xml", "uk", "confluence"),
    ]

    artefacts: list[C1Sourceartefact] = []
    for artefact_id, content, media_type, region, system in fixtures:
        artefact = make_artefact(artefact_id=artefact_id, region=region, system=system, content=content, media_type=media_type)
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
    return manifest, evidence_store, run_store


class TestIngestArtefacts:
    def test_produces_real_attributes_chunks_nodes_and_edges(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        result = ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        # OpenAPI (Claim) + XSD (6 complex types/elements) contribute real
        # attributes via parsers/router.py; WSDL/Avro/Confluence's own
        # attribute contribution depends on what each real parser finds -
        # what matters here is that SOME real attributes were produced,
        # not a specific brittle count.
        assert result.attributes_written > 0
        assert result.chunks_written > 0
        assert result.nodes_written > 0
        assert result.edges_written > 0
        assert result.chunks_skipped_idempotent == 0

    def test_confluence_artefact_is_chunked_but_contributes_no_attributes(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        # parsers/router.py has no registered parser for Confluence's
        # media type - ingest_artefacts must not treat that as fatal.
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        with substrate_db.connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM chunks WHERE artefact_id = %s", ("art-confluence",)
            ).fetchone()
        assert row is not None and row[0] > 0

        attributes = run_store.read_attributes(manifest.runId)
        assert all("art-confluence" not in a.sourceContract for a in attributes)

    def test_attributes_are_persisted_to_run_store_sharded_by_region(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        uk_attributes = run_store.read_attributes(manifest.runId, "uk")
        us_attributes = run_store.read_attributes(manifest.runId, "us")
        assert len(uk_attributes) > 0
        # Avro's own artefact was seeded under region "us".
        assert all(a.region.value == "us" for a in us_attributes)
        assert all(a.region.value == "uk" for a in uk_attributes)

    def test_every_attribute_gets_an_artefact_evidenced_by_edge(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        attributes = run_store.read_attributes(manifest.runId)
        with substrate_db.connection() as conn:
            for attribute in attributes:
                row = conn.execute(
                    "SELECT 1 FROM edges WHERE from_id = %s AND edge_type = 'EVIDENCED_BY'",
                    (attribute.attributeId,),
                ).fetchone()
                assert row is not None

    def test_re_ingesting_unchanged_content_skips_the_embed_call_via_idempotent_chunks(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        first = ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        assert first.chunks_skipped_idempotent == 0

        second = ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )
        assert second.chunks_written == 0
        assert second.chunks_skipped_idempotent == first.chunks_written

    def test_embed_fn_is_not_called_for_an_already_present_chunk(self, tmp_path: Path, substrate_db: SubstrateDb) -> None:
        manifest, evidence_store, run_store = _seed_manifest_and_evidence(tmp_path)
        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
        )

        calls: list[str] = []

        def _tracking_embed(text: str, dimensions: int) -> list[float]:
            calls.append(text)
            return [0.0] * dimensions

        ingest_artefacts(
            manifest.runId, manifest,
            evidence_store=evidence_store, run_store=run_store, db=substrate_db, dimensions=DIMENSIONS,
            embed_fn=_tracking_embed,
        )
        # Every chunk was already present from the first ingest run, so
        # the chunk-embedding branch of _tracking_embed is never reached -
        # only attribute-embedding calls (which always re-run) show up.
        attributes = run_store.read_attributes(manifest.runId)
        assert len(calls) == len(attributes)
