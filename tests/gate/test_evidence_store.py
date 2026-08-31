from __future__ import annotations

import hashlib
from pathlib import Path

from gate.evidence_store import EvidenceStore


def _hash_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class TestEvidenceStore:
    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        store = EvidenceStore(base_path=tmp_path)
        content = b"redacted artefact bytes"
        content_hash = _hash_of(content)
        store.write_artefact(content_hash, content)
        assert store.read_artefact(content_hash) == content

    def test_path_is_sharded_by_first_two_hash_characters(self, tmp_path: Path) -> None:
        store = EvidenceStore(base_path=tmp_path)
        content = b"some bytes"
        content_hash = _hash_of(content)
        path = store.write_artefact(content_hash, content)
        assert path == tmp_path / "artefacts" / content_hash[:2] / content_hash

    def test_has_artefact_false_before_write_true_after(self, tmp_path: Path) -> None:
        store = EvidenceStore(base_path=tmp_path)
        content = b"content"
        content_hash = _hash_of(content)
        assert store.has_artefact(content_hash) is False
        store.write_artefact(content_hash, content)
        assert store.has_artefact(content_hash) is True

    def test_writing_the_same_hash_twice_is_idempotent_and_does_not_error(self, tmp_path: Path) -> None:
        store = EvidenceStore(base_path=tmp_path)
        content = b"content"
        content_hash = _hash_of(content)
        store.write_artefact(content_hash, content)
        store.write_artefact(content_hash, content)
        assert store.read_artefact(content_hash) == content
