from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from pipeline.run_store import RunStore


def _manifest(run_id: UUID) -> C4Corpusmanifest:
    return C4Corpusmanifest.model_validate({
        "runId": str(run_id),
        "domain": "claims",
        "sealedAt": "2026-08-20T10:00:00Z",
        "corpusHash": "a" * 64,
        "artefacts": [],
        "exclusions": [],
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
