from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C11.JournalEvent._1_0 import C11Journalevent
from pipeline.run_store import RunStore, TriageEntry


def _manifest(run_id: UUID) -> C4Corpusmanifest:
    return C4Corpusmanifest.model_validate({
        "runId": str(run_id),
        "domain": "claims",
        "sealedAt": "2026-08-20T10:00:00Z",
        "corpusHash": "a" * 64,
        "artefacts": [],
        "exclusions": [],
    })


def _attribute(run_id: UUID, *, region: str = "uk", path: str = "claim.claimId") -> C5Attributerecord:
    return C5Attributerecord.model_validate({
        "attributeId": f"attr://{region}/art-1/{path}",
        "runId": str(run_id),
        "region": region,
        "sourceContract": "art-1",
        "path": path,
        "localName": path.rsplit(".", 1)[-1],
        "dataType": "string",
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/art-1@{'a' * 16}#/{path}"],
    })


def _journal_event(run_id: UUID, *, seq: int) -> C11Journalevent:
    return C11Journalevent.model_validate({
        "runId": str(run_id),
        "seq": seq,
        "at": "2026-08-31T12:00:00Z",
        "kind": "stage.transition",
        "stage": "S1",
        "outcome": "ok",
    })


class TestRunStore:
    def test_write_creates_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.write_corpus_manifest(run_id, _manifest(run_id))
        assert destination == tmp_path / str(run_id) / "S1" / "corpus_manifest.json"
        assert destination.is_file()

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        original = _manifest(run_id)
        store.write_corpus_manifest(run_id, original)

        reread = store.read_corpus_manifest(run_id)
        assert reread.runId == original.runId
        assert reread.corpusHash == original.corpusHash
        assert reread == original

    def test_relative_base_path_resolves_against_repo_root(self) -> None:
        store = RunStore(base_path="run-store")
        assert store.run_dir(uuid4()).is_absolute()

    def test_absolute_base_path_used_as_is(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        assert store.run_dir(run_id) == tmp_path / str(run_id)


class TestWriteAndReadAttributes:
    def test_write_creates_the_expected_shard_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.write_attributes(run_id, "uk", [_attribute(run_id)])
        assert destination == tmp_path / str(run_id) / "S3" / "attributes" / "uk.jsonl"
        assert destination.is_file()

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        records = [_attribute(run_id, path="claim.claimId"), _attribute(run_id, path="claim.lossDate")]
        store.write_attributes(run_id, "uk", records)

        reread = store.read_attributes(run_id, "uk")
        assert [r.attributeId for r in reread] == [r.attributeId for r in records]

    def test_read_with_no_region_concatenates_every_shard(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_attributes(run_id, "uk", [_attribute(run_id, region="uk", path="claim.claimId")])
        store.write_attributes(run_id, "us", [_attribute(run_id, region="us", path="claim.claimId")])

        reread = store.read_attributes(run_id)
        assert {r.region.value for r in reread} == {"uk", "us"}

    def test_read_for_a_region_with_no_shard_returns_an_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_attributes(uuid4(), "eu") == []

    def test_write_is_a_full_overwrite_not_an_append(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_attributes(run_id, "uk", [_attribute(run_id, path="claim.claimId")])
        store.write_attributes(run_id, "uk", [_attribute(run_id, path="claim.lossDate")])
        reread = store.read_attributes(run_id, "uk")
        assert len(reread) == 1
        assert reread[0].path == "claim.lossDate"

    def test_writing_an_empty_list_produces_an_empty_shard(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.write_attributes(run_id, "uk", [])
        assert store.read_attributes(run_id, "uk") == []


class TestAppendJournalEvent:
    def test_append_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        destination = store.append_journal_event(run_id, _journal_event(run_id, seq=0))
        assert destination == tmp_path / str(run_id) / "journal.jsonl"
        assert destination.is_file()

    def test_repeated_appends_accumulate_not_overwrite(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.append_journal_event(run_id, _journal_event(run_id, seq=0))
        store.append_journal_event(run_id, _journal_event(run_id, seq=1))
        path = tmp_path / str(run_id) / "journal.jsonl"
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_appended_lines_are_valid_journal_events(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.append_journal_event(run_id, _journal_event(run_id, seq=0))
        path = tmp_path / str(run_id) / "journal.jsonl"
        line = path.read_text(encoding="utf-8").strip().splitlines()[0]
        reread = C11Journalevent.model_validate(json.loads(line))
        assert reread.seq == 0
        assert reread.kind == "stage.transition"


class TestAppendAndReadTriageEntries:
    def test_append_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        entry = TriageEntry(kind="review-pair", reason="score in review band", member_attribute_ids=("a", "b"), score=0.6)
        destination = store.append_triage_entry(run_id, entry)
        assert destination == tmp_path / str(run_id) / "S4" / "triage.jsonl"
        assert destination.is_file()

    def test_read_with_no_entries_returns_empty_list(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        assert store.read_triage_entries(uuid4()) == []

    def test_read_after_append_round_trips(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        entry = TriageEntry(
            kind="review-pair",
            reason="score in review band",
            member_attribute_ids=("attr://us/art-1/Claim.a", "attr://uk/art-2/Claim.b"),
            score=0.61,
            features={"lexical": 0.5},
        )
        store.append_triage_entry(run_id, entry)
        reread = store.read_triage_entries(run_id)
        assert reread == [entry]

    def test_repeated_appends_accumulate(self, tmp_path: Path) -> None:
        store = RunStore(base_path=tmp_path)
        run_id = uuid4()
        store.append_triage_entry(run_id, TriageEntry(kind="review-pair", reason="r1", member_attribute_ids=("a", "b")))
        store.append_triage_entry(
            run_id, TriageEntry(kind="agent-escalation", reason="homonym", member_attribute_ids=("c",), cluster_payload={"x": 1})
        )
        reread = store.read_triage_entries(run_id)
        assert len(reread) == 2
        assert reread[0].kind == "review-pair"
        assert reread[1].kind == "agent-escalation"
        assert reread[1].cluster_payload == {"x": 1}
