"""
Hermetic tests for api/registry.py - Section 12.3's registry API, over a
real fastapi.testclient.TestClient. The gate-check path (POST .../releases)
reuses a real orchestrator run (create_run() over the golden corpus,
proven at tests/pipeline/test_orchestrator.py) rather than a stand-in -
"coverage gates not satisfied" needs a real, computed CoverageReport to
mean anything.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C11.RunManifest._1_0 import C11Runmanifest

from config.settings import load_settings
from emit.release import ReleaseManifest, build_release_manifest
from pipeline.registry_store import RegistryStore
from pipeline.run_store import RunStore

from api.app import create_app

pytestmark = pytest.mark.e2e

_EVREF = f"evref://uk/git/art-1@{'a' * 16}#/x"


def _client(tmp_path: Path) -> TestClient:
    app = create_app(settings=load_settings(), base_path=tmp_path, require_auth=False)
    return TestClient(app)


def _create_run(client: TestClient) -> str:
    response = client.post(
        "/v1/runs",
        json={"domain": "claims", "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"}},
    )
    assert response.status_code == 201, response.text
    run_id: str = response.json()["runId"]
    return run_id


def _attribute(region: str) -> C5Attributerecord:
    return C5Attributerecord.model_validate({
        "attributeId": f"attr://{region}/art-1/Claim.claimId",
        "runId": "b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44", "region": region, "sourceContract": "art-1",
        "path": "Claim.claimId", "localName": "claimId", "dataType": "string", "cardinality": "1..1",
        "obligation": {"level": "mandatory"}, "evidenceTier": 1, "inferred": False, "evidenceRefs": [_EVREF],
    })


def _seed_passing_universe(tmp_path: Path, run_id: str) -> None:
    """Writes one fully-covered, ratified cluster+candidate (plus the
    real attribute records SubstrateApi.get_attribute needs to resolve
    them) directly to the on-disk RunStore - self-contained, no real
    create_run() call, and no other real clusters left unresolved to
    confuse the gate outcome. This test file's own job is the registry
    router's gate-check and release-creation logic, not re-proving
    coverage()'s own arithmetic (tests/algorithms/test_coverage.py and
    its own acceptance test already do that exhaustively)."""
    store = RunStore(base_path=tmp_path / "run-store")
    run_uuid = UUID(run_id)

    manifest = C11Runmanifest.model_validate({
        "runId": run_id, "domain": "claims",
        "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
        "corpusHash": "a" * 64,
        "pins": {"prompts": {}, "models": {}, "tools": {}, "algorithms": {}},
        "parameters": {}, "budget": {"tokensTotal": 1000, "costCeilingGbp": 10.0, "perStage": {}},
        "state": "CANDIDATES_READY", "createdBy": "tester",
    })
    store.write_run_manifest(run_uuid, manifest)

    for region in ("us", "uk", "eu"):
        store.write_attributes(run_uuid, region, [_attribute(region)])

    cluster = C6Conceptcluster.model_validate({
        "clusterId": "cluster://claim-id",
        "proposedConcept": "claimId",
        "members": [
            {"attributeId": "attr://us/art-1/Claim.claimId", "region": "us", "role": "core", "pairScore": 1.0},
            {"attributeId": "attr://uk/art-1/Claim.claimId", "region": "uk", "role": "variant", "pairScore": 1.0},
            {"attributeId": "attr://eu/art-1/Claim.claimId", "region": "eu", "role": "variant", "pairScore": 1.0},
        ],
        "confidence": 0.95,
        "evidenceRefs": [_EVREF],
    })
    candidate = C8Canonicalcandidate.model_validate({
        "candidateId": "canon://Claim.claimId", "entity": "Claim", "attribute": "claimId",
        "dataType": "string", "cardinality": "1..1", "obligation": {"level": "mandatory"},
        "placement": "core", "placementRule": "1", "namingSource": "derived", "rationale": "x",
        "clusterRefs": ["cluster://claim-id"], "weight": 5,
        "ratification": {"status": "approved", "sme": "jane.doe@example.com", "decidedAt": "2026-08-20T09:00:00Z"},
    })
    store.write_clusters(run_uuid, [cluster])
    store.write_candidates(run_uuid, [candidate])


class TestListAndGetReleases:
    def test_list_releases_for_an_unknown_domain_is_an_empty_list(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/releases")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_unknown_release_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/releases/9.9.9")
        assert response.status_code == 404

    def test_get_unknown_artefact_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/releases/9.9.9/artefacts/Claim.json")
        assert response.status_code == 404


class TestCreateRelease:
    def test_create_release_before_clustering_is_gates_not_satisfied(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/v1/registry/claims/releases",
            json={"runId": "00000000-0000-0000-0000-000000000000", "semver": "1.0.0"},
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith("/gates-not-satisfied")

    def test_create_release_with_no_candidates_fails_gate1(self, tmp_path: Path) -> None:
        # Gate 1 needs no unresolved weight-5 concept; a run that never
        # advanced past TRIAGE has zero candidates, so every real
        # weight-5 cluster is an unresolved gap - a genuine, expected
        # gate failure, not a stand-in.
        client = _client(tmp_path)
        run_id = _create_run(client)
        response = client.post("/v1/registry/claims/releases", json={"runId": run_id, "semver": "1.0.0"})
        assert response.status_code == 422
        assert response.json()["type"].endswith("/gates-not-satisfied")

    def test_create_release_with_a_fully_covered_universe_succeeds(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        run_id = "b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44"
        _seed_passing_universe(tmp_path, run_id)

        response = client.post(
            "/v1/registry/claims/releases",
            json={
                "runId": run_id, "semver": "1.0.0",
                "approvers": [{"role": "ARB", "name": "Jane", "at": "2026-09-30T14:05:00Z"}],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["coverage"]["gate1"] is True
        assert body["coverage"]["gate2"] is True
        assert body["coverage"]["gate3"] is True

        listed = client.get("/v1/registry/claims/releases")
        assert [r["semver"] for r in listed.json()] == ["1.0.0"]

        fetched = client.get("/v1/registry/claims/releases/1.0.0")
        assert fetched.status_code == 200
        assert fetched.json()["runId"] == run_id


def _manifest(version: str, artefacts: list[tuple[str, bytes]]) -> ReleaseManifest:
    return build_release_manifest(
        domain="claims", version=version, run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44",
        corpus_hash="sha256:abc", pins={}, artefacts=artefacts, coverage_score=0.95,
        gate1=True, gate2=True, gate3=True, acord_conformance=0.0,
        signed_at="2026-01-01T00:00:00+00:00", signature="sig:placeholder",
    )


class TestDiff:
    def test_diff_between_unknown_releases_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/diff", params={"from": "1.0.0", "to": "1.1.0"})
        assert response.status_code == 404

    def test_diff_reports_added_changed_removed_and_breaking_for_a_real_core_change(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path / "registry-store")
        store.write_release("claims", _manifest("1.0.0", [
            ("Claim.json", b'{"a":1}'), ("Incident.json", b"{}"), ("extensions/uk/ClaimExtension.json", b"{}"),
        ]))
        store.write_release("claims", _manifest("1.1.0", [
            ("Claim.json", b'{"a":2}'), ("PolicyContext.json", b"{}"), ("extensions/uk/ClaimExtension.json", b'{"x":1}'),
        ]))

        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/diff", params={"from": "1.0.0", "to": "1.1.0"})
        assert response.status_code == 200
        body = response.json()
        assert body["added"] == ["PolicyContext.json"]
        assert body["removed"] == ["Incident.json"]
        assert set(body["changed"]) == {"Claim.json", "extensions/uk/ClaimExtension.json"}
        assert body["breaking"] is True  # Claim.json (core) changed

    def test_diff_over_extension_only_changes_is_not_breaking(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path / "registry-store")
        store.write_release("claims", _manifest("1.0.0", [("extensions/uk/ClaimExtension.json", b"{}")]))
        store.write_release("claims", _manifest("1.1.0", [("extensions/uk/ClaimExtension.json", b'{"x":1}')]))

        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/diff", params={"from": "1.0.0", "to": "1.1.0"})
        assert response.json()["breaking"] is False


class TestArtefacts:
    def test_write_and_read_a_real_release_artefact(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path / "registry-store")
        store.write_release("claims", _manifest("1.0.0", []))
        store.write_artefact("claims", "1.0.0", "Claim.json", b'{"a":1}', "application/schema+json")

        client = _client(tmp_path)
        response = client.get("/v1/registry/claims/releases/1.0.0/artefacts/Claim.json")
        assert response.status_code == 200
        assert response.content == b'{"a":1}'
        assert response.headers["content-type"] == "application/schema+json"
