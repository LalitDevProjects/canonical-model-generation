"""Hermetic tests for pipeline/run_store.py's Section-12-driven extensions:
RunManifest read/write/state-update/listing, journal read-back,
cluster/candidate persistence, and generalised checkpoint sealing/decisions."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C11.JournalEvent._1_0 import C11Journalevent
from generated.C11.RunManifest._1_0 import C11Runmanifest
from pipeline.run_store import RunStore


def _manifest(run_id: UUID, *, domain: str = "claims", state: str = "CREATED") -> C11Runmanifest:
    return C11Runmanifest.model_validate({
        "runId": str(run_id),
        "domain": domain,
        "trigger": {"kind": "manual", "requestedBy": "tester", "at": "2026-08-31T12:00:00Z"},
        "corpusHash": "0" * 64,
        "pins": {"prompts": {}, "models": {}, "tools": {}, "algorithms": {}},
        "parameters": {},
        "budget": {"tokensTotal": 1_000_000, "costCeilingGbp": 100.0, "perStage": {}},
        "state": state,
        "createdBy": "tester",
    })


def _cluster(cluster_id: str = "claim-id") -> C6Conceptcluster:
    return C6Conceptcluster.model_validate({
        "clusterId": f"cluster://{cluster_id}",
        "proposedConcept": cluster_id,
        "members": [{"attributeId": "attr://uk/art-1/Claim.x", "region": "uk", "role": "core", "pairScore": 1.0}],
        "confidence": 0.9,
        "evidenceRefs": [f"evref://uk/git/art-1@{'a' * 16}#/x"],
    })


def _candidate(attribute: str = "claimId") -> C8Canonicalcandidate:
    return C8Canonicalcandidate.model_validate({
        "candidateId": f"canon://Claim.{attribute}",
        "entity": "Claim",
        "attribute": attribute,
        "dataType": "string",
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "placement": "core",
        "placementRule": "1",
        "namingSource": "derived",
        "rationale": "x",
        "clusterRefs": ["cluster://claim-id"],
        "weight": 5,
        "ratification": {"status": "pending", "sme": None, "decidedAt": None},
    })


def _journal_event(run_id: UUID, *, seq: int) -> C11Journalevent:
    return C11Journalevent.model_validate({
        "runId": str(run_id), "seq": seq, "at": "2026-08-31T12:00:00Z", "kind": "stage.transition", "stage": "S1", "outcome": "ok",
    })


class TestRunManifest:
    def test_write_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.write_run_manifest(run_id, _manifest(run_id))
        assert destination == tmp_path / str(run_id) / "manifest.json"
        assert destination.is_file()

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        original = _manifest(run_id)
        store.write_run_manifest(run_id, original)
        assert store.read_run_manifest(run_id) == original

    def test_update_state_persists_and_returns_the_updated_manifest(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_run_manifest(run_id, _manifest(run_id, state="CREATED"))
        updated = store.update_run_state(run_id, "AWAIT_TRIAGE")
        assert updated.state == "AWAIT_TRIAGE"
        assert store.read_run_manifest(run_id).state == "AWAIT_TRIAGE"

    def test_update_state_only_changes_state_field(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        original = _manifest(run_id)
        store.write_run_manifest(run_id, original)
        updated = store.update_run_state(run_id, "PAUSED")
        assert updated.domain == original.domain
        assert updated.corpusHash == original.corpusHash

    def test_repeated_writes_overwrite_not_append(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_run_manifest(run_id, _manifest(run_id, state="CREATED"))
        store.write_run_manifest(run_id, _manifest(run_id, state="RUNNING"))
        assert store.read_run_manifest(run_id).state == "RUNNING"


class TestListRuns:
    def test_lists_every_run_with_a_manifest(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        a, b = uuid4(), uuid4()
        store.write_run_manifest(a, _manifest(a))
        store.write_run_manifest(b, _manifest(b))
        assert {m.runId for m in store.list_runs()} == {a, b}

    def test_filters_by_domain(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        a, b = uuid4(), uuid4()
        store.write_run_manifest(a, _manifest(a, domain="claims"))
        store.write_run_manifest(b, _manifest(b, domain="policy"))
        assert [m.runId for m in store.list_runs(domain="claims")] == [a]

    def test_empty_base_path_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path / "does-not-exist-yet")
        assert store.list_runs() == []

    def test_a_run_dir_with_no_manifest_yet_is_skipped(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_attributes(run_id, "uk", [])  # creates the run dir with no manifest.json
        assert store.list_runs() == []


class TestReadJournalEvents:
    def test_read_with_no_journal_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_journal_events(uuid4()) == []

    def test_read_after_appends_round_trips_in_order(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.append_journal_event(run_id, _journal_event(run_id, seq=0))
        store.append_journal_event(run_id, _journal_event(run_id, seq=1))
        events = store.read_journal_events(run_id)
        assert [e.seq for e in events] == [0, 1]

    def test_from_seq_filters_earlier_events(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        for seq in range(4):
            store.append_journal_event(run_id, _journal_event(run_id, seq=seq))
        events = store.read_journal_events(run_id, from_seq=2)
        assert [e.seq for e in events] == [2, 3]

    def test_limit_caps_the_result(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        for seq in range(4):
            store.append_journal_event(run_id, _journal_event(run_id, seq=seq))
        events = store.read_journal_events(run_id, limit=2)
        assert [e.seq for e in events] == [0, 1]

    def test_a_blank_line_in_the_journal_file_is_skipped(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.append_journal_event(run_id, _journal_event(run_id, seq=0))
        path = tmp_path / str(run_id) / "journal.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert [e.seq for e in store.read_journal_events(run_id)] == [0]


class TestClusters:
    def test_write_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.write_clusters(run_id, [_cluster()])
        assert destination == tmp_path / str(run_id) / "S4" / "clusters.jsonl"

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        clusters = [_cluster("claim-id"), _cluster("loss-date")]
        store.write_clusters(run_id, clusters)
        reread = store.read_clusters(run_id)
        assert [c.clusterId for c in reread] == [c.clusterId for c in clusters]

    def test_read_with_no_clusters_written_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_clusters(uuid4()) == []

    def test_writing_an_empty_list_produces_an_empty_shard(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_clusters(run_id, [])
        assert store.read_clusters(run_id) == []


class TestCandidates:
    def test_write_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.write_candidates(run_id, [_candidate()])
        assert destination == tmp_path / str(run_id) / "S6" / "candidates.jsonl"

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        candidates = [_candidate("claimId"), _candidate("lossDate")]
        store.write_candidates(run_id, candidates)
        reread = store.read_candidates(run_id)
        assert [c.candidateId for c in reread] == [c.candidateId for c in candidates]

    def test_read_with_no_candidates_written_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_candidates(uuid4()) == []


class TestCheckpointSealing:
    def test_seal_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.seal_checkpoint(run_id, "TRIAGE", items=[{"itemId": "x"}], corpus_hash="a" * 64)
        assert destination == tmp_path / str(run_id) / "checkpoints" / "TRIAGE" / "sealed.json"

    def test_read_after_seal_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.seal_checkpoint(run_id, "TRIAGE", items=[{"itemId": "x"}], corpus_hash="a" * 64)
        sealed = store.read_sealed_checkpoint(run_id, "TRIAGE")
        assert sealed is not None
        assert sealed["checkpoint"] == "TRIAGE"
        assert sealed["corpusHashAtSeal"] == "a" * 64
        assert sealed["items"] == [{"itemId": "x"}]

    def test_read_unsealed_checkpoint_returns_none(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_sealed_checkpoint(uuid4(), "TRIAGE") is None

    def test_re_sealing_overwrites_not_appends(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.seal_checkpoint(run_id, "TRIAGE", items=[{"itemId": "x"}], corpus_hash="a" * 64)
        store.seal_checkpoint(run_id, "TRIAGE", items=[{"itemId": "y"}], corpus_hash="b" * 64)
        sealed = store.read_sealed_checkpoint(run_id, "TRIAGE")
        assert sealed is not None
        assert sealed["items"] == [{"itemId": "y"}]

    def test_different_checkpoints_are_independent(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.seal_checkpoint(run_id, "TRIAGE", items=[{"itemId": "x"}], corpus_hash="a" * 64)
        assert store.read_sealed_checkpoint(run_id, "RATIFY") is None


class TestCheckpointDecisions:
    def test_read_with_no_decisions_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_checkpoint_decisions(uuid4(), "TRIAGE") == []

    def test_complete_is_false_with_no_decisions(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.checkpoint_decisions_complete(uuid4(), "TRIAGE") is False

    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        decisions = [{"itemId": "x", "outcome": "accept", "rationale": "r", "decidedBy": "sme"}]
        store.write_checkpoint_decisions(run_id, "TRIAGE", decisions, complete=False)
        assert store.read_checkpoint_decisions(run_id, "TRIAGE") == decisions

    def test_multiple_batches_accumulate(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_checkpoint_decisions(run_id, "TRIAGE", [{"itemId": "x"}], complete=False)
        store.write_checkpoint_decisions(run_id, "TRIAGE", [{"itemId": "y"}], complete=True)
        assert store.read_checkpoint_decisions(run_id, "TRIAGE") == [{"itemId": "x"}, {"itemId": "y"}]

    def test_complete_reflects_only_the_last_submitted_batch(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_checkpoint_decisions(run_id, "TRIAGE", [{"itemId": "x"}], complete=True)
        assert store.checkpoint_decisions_complete(run_id, "TRIAGE") is True
        store.write_checkpoint_decisions(run_id, "TRIAGE", [{"itemId": "y"}], complete=False)
        assert store.checkpoint_decisions_complete(run_id, "TRIAGE") is False
