"""
Hermetic tests for api/run_control.py - Section 12.2's run-control API,
exercised through a real fastapi.testclient.TestClient (no live server
process, no live network) against the real orchestrator and a
tmp_path-rooted RunStore. Every route calls real code end to end - the
same golden-corpus-backed path tests/pipeline/test_orchestrator.py
already proves at the orchestrator layer, wired here through real HTTP
request/response handling instead.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from config.settings import load_settings
from pipeline.run_store import RunStore

from api.app import create_app

pytestmark = pytest.mark.e2e


def _client(tmp_path: Path) -> TestClient:
    app = create_app(settings=load_settings(), base_path=tmp_path, require_auth=False)
    return TestClient(app)


def _create_run(client: TestClient, domain: str = "claims") -> dict[str, str]:
    response = client.post(
        "/v1/runs",
        json={"domain": domain, "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"}},
    )
    assert response.status_code == 201, response.text
    result: dict[str, str] = response.json()
    return result


class TestCreateRun:
    def test_returns_201_with_a_real_run_id_and_await_triage_state(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        body = _create_run(client)
        assert body["state"] == "AWAIT_TRIAGE"
        assert len(body["runId"]) == 36  # a real UUID string

    def test_unsupported_domain_is_400_invalid_contract(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post(
            "/v1/runs",
            json={"domain": "policy", "trigger": {"kind": "manual", "requestedBy": "t", "at": "2026-08-31T12:00:00Z"}},
        )
        assert response.status_code == 400
        assert response.json()["type"].endswith("/invalid-contract")

    def test_second_create_for_the_same_active_domain_is_409_run_conflict(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        _create_run(client)
        response = client.post(
            "/v1/runs",
            json={"domain": "claims", "trigger": {"kind": "manual", "requestedBy": "t", "at": "2026-08-31T12:00:00Z"}},
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/run-conflict")

    def test_repeated_idempotency_key_returns_the_original_result_not_a_second_run(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        payload = {"domain": "claims", "trigger": {"kind": "manual", "requestedBy": "t", "at": "2026-08-31T12:00:00Z"}}
        first = client.post("/v1/runs", json=payload, headers={"Idempotency-Key": "abc"})
        second = client.post("/v1/runs", json=payload, headers={"Idempotency-Key": "abc"})
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json() == second.json()

    def test_malformed_body_is_a_422_from_fastapis_own_validation(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.post("/v1/runs", json={"domain": "claims"})  # missing required trigger
        assert response.status_code == 422


class TestGetRun:
    def test_returns_the_real_persisted_manifest(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}")
        assert response.status_code == 200
        assert response.json()["domain"] == "claims"
        assert response.json()["state"] == "AWAIT_TRIAGE"

    def test_unknown_run_id_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/runs/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert response.json()["type"].endswith("/not-found")


class TestJournal:
    def test_returns_real_stage_transition_events_in_order(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/journal")
        assert response.status_code == 200
        stages = [e["stage"] for e in response.json()["events"]]
        assert stages == ["S1", "S3", "S4", "S4"]

    def test_from_seq_filters_earlier_events(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/journal", params={"fromSeq": 2})
        events = response.json()["events"]
        assert all(e["seq"] >= 2 for e in events)

    def test_limit_returns_a_continuation_cursor(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/journal", params={"limit": 2})
        body = response.json()
        assert len(body["events"]) == 2
        assert body["nextCursor"] is not None


class TestPauseResume:
    def test_pause_then_resume_round_trips_through_running(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        run_id = created["runId"]

        paused = client.post(f"/v1/runs/{run_id}/pause")
        assert paused.status_code == 201
        assert paused.json()["state"] == "PAUSED"

        resumed = client.post(f"/v1/runs/{run_id}/resume")
        assert resumed.status_code == 201
        assert resumed.json()["state"] == "RUNNING"

    def test_resume_on_a_non_paused_run_is_a_no_op(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.post(f"/v1/runs/{created['runId']}/resume")
        assert response.json()["state"] == "AWAIT_TRIAGE"


class TestCheckpointsAndDecisions:
    def test_submit_decisions_against_an_unsealed_checkpoint_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/RATIFY/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 404

    def test_get_sealed_triage_checkpoint_returns_real_review_band_items(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/checkpoints/TRIAGE")
        assert response.status_code == 200
        assert response.json()["checkpoint"] == "TRIAGE"
        assert len(response.json()["items"]) > 0

    def test_get_unsealed_checkpoint_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/checkpoints/RATIFY")
        assert response.status_code == 404

    def test_submit_decisions_with_complete_true_resumes_the_run(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 202
        assert response.json()["runState"] == "AWAIT_MODEL_PROVIDER"

    def test_submit_decisions_with_complete_false_does_not_resume(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": False},
        )
        assert response.status_code == 202
        assert response.json()["runState"] == "AWAIT_TRIAGE"

    def test_corpus_drift_since_seal_is_409(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)

        # Drift the corpus hash directly through the same on-disk
        # RunStore the app itself reads from (same base_path).
        store = RunStore(base_path=tmp_path / "run-store")
        drifted = store.read_run_manifest(UUID(created["runId"])).model_copy(update={"corpusHash": "f" * 64})
        store.write_run_manifest(UUID(created["runId"]), drifted)

        response = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/TRIAGE/decisions",
            json={"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True},
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/corpus-drift")

    def test_decisions_idempotency_key_replay_does_not_double_submit(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        payload = {"decisions": [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}], "complete": True}
        first = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/TRIAGE/decisions", json=payload, headers={"Idempotency-Key": "k1"}
        )
        second = client.post(
            f"/v1/runs/{created['runId']}/checkpoints/TRIAGE/decisions", json=payload, headers={"Idempotency-Key": "k1"}
        )
        assert first.json() == second.json()


def _seed_bare_manifest(tmp_path: Path, run_id: str) -> None:
    """A real, persisted RunManifest with no clusters written yet -
    distinct from a run_id that doesn't exist at all (_get_run_or_404's
    own 404), needed to exercise coverage/gaps' own "not reached
    clustering yet" 404 branch specifically."""
    from generated.C11.RunManifest._1_0 import C11Runmanifest

    store = RunStore(base_path=tmp_path / "run-store")
    store.write_run_manifest(UUID(run_id), C11Runmanifest.model_validate({
        "runId": run_id, "domain": "claims",
        "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
        "corpusHash": "a" * 64,
        "pins": {"prompts": {}, "models": {}, "tools": {}, "algorithms": {}},
        "parameters": {}, "budget": {"tokensTotal": 1000, "costCeilingGbp": 10.0, "perStage": {}},
        "state": "RUNNING", "createdBy": "tester",
    }))


class TestCoverageAndGaps:
    def test_coverage_for_an_unknown_run_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        response = client.get("/v1/runs/00000000-0000-0000-0000-000000000000/coverage")
        assert response.status_code == 404

    def test_coverage_before_clustering_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        run_id = "11111111-1111-1111-1111-111111111111"
        _seed_bare_manifest(tmp_path, run_id)
        response = client.get(f"/v1/runs/{run_id}/coverage")
        assert response.status_code == 404

    def test_gaps_before_clustering_is_404(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        run_id = "11111111-1111-1111-1111-111111111111"
        _seed_bare_manifest(tmp_path, run_id)
        response = client.get(f"/v1/runs/{run_id}/gaps")
        assert response.status_code == 404

    def test_coverage_after_create_run_returns_a_real_report(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/coverage")
        assert response.status_code == 200
        body = response.json()
        assert body["domain"] == "claims"
        assert "gate1Pass" in body

    def test_gaps_after_create_run_returns_real_gap_entries(self, tmp_path: Path) -> None:
        client = _client(tmp_path)
        created = _create_run(client)
        response = client.get(f"/v1/runs/{created['runId']}/gaps")
        assert response.status_code == 200
        assert isinstance(response.json()["gaps"], list)
