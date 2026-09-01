from __future__ import annotations

from pathlib import Path

from emit.release import ReleaseManifest, build_release_manifest
from pipeline.registry_store import RegistryStore


def _manifest(*, version: str = "1.0.0", signed_at: str = "2026-01-01T00:00:00+00:00") -> ReleaseManifest:
    return build_release_manifest(
        domain="claims", version=version, run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44",
        corpus_hash="sha256:abc", pins={}, artefacts=[("Claim.json", b'{"a":1}')],
        coverage_score=0.95, gate1=True, gate2=True, gate3=True, acord_conformance=0.0,
        signed_at=signed_at, signature="sig:placeholder",
    )


class TestWriteAndReadRelease:
    def test_write_creates_the_expected_path(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        destination = store.write_release("claims", _manifest())
        assert destination == tmp_path / "claims" / "releases" / "1.0.0" / "manifest.json"
        assert destination.is_file()

    def test_read_after_write_round_trips(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        original = _manifest()
        store.write_release("claims", original)
        assert store.read_release("claims", "1.0.0") == original

    def test_relative_base_path_resolves_against_repo_root(self) -> None:
        store = RegistryStore(base_path="registry-store")
        assert store.release_dir("claims", "1.0.0").is_absolute()


class TestListReleases:
    def test_empty_domain_returns_empty_list(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        assert store.list_releases("claims") == []

    def test_lists_ordered_by_signed_at_ascending(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        newer = _manifest(version="1.1.0", signed_at="2026-02-01T00:00:00+00:00")
        older = _manifest(version="1.0.0", signed_at="2026-01-01T00:00:00+00:00")
        store.write_release("claims", newer)
        store.write_release("claims", older)
        assert [m.version for m in store.list_releases("claims")] == ["1.0.0", "1.1.0"]

    def test_different_domains_are_independent(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        store.write_release("claims", _manifest())
        assert store.list_releases("policy") == []


class TestArtefacts:
    def test_write_then_read_round_trips_content_and_media_type(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        store.write_artefact("claims", "1.0.0", "Claim.json", b'{"x":1}', "application/schema+json")
        content, media_type = store.read_artefact("claims", "1.0.0", "Claim.json")
        assert content == b'{"x":1}'
        assert media_type == "application/schema+json"

    def test_nested_artefact_path_is_supported(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        store.write_artefact("claims", "1.0.0", "extensions/uk/ClaimExtension.json", b"{}", "application/schema+json")
        content, media_type = store.read_artefact("claims", "1.0.0", "extensions/uk/ClaimExtension.json")
        assert content == b"{}"

    def test_media_type_defaults_when_sidecar_missing(self, tmp_path: Path) -> None:
        store = RegistryStore(base_path=tmp_path)
        destination = tmp_path / "claims" / "releases" / "1.0.0" / "artefacts" / "raw.bin"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"\x00\x01")
        content, media_type = store.read_artefact("claims", "1.0.0", "raw.bin")
        assert content == b"\x00\x01"
        assert media_type == "application/octet-stream"
