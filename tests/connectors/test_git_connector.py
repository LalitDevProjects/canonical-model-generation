from __future__ import annotations

import subprocess
from pathlib import Path

from connectors.base import ConnectorScope
from connectors.git_connector import GitConnector, guess_media_type


class TestGuessMediaType:
    def test_yaml_extension(self) -> None:
        assert guess_media_type("claims-us/openapi.yaml") == "application/yaml"

    def test_json_extension(self) -> None:
        assert guess_media_type("page.json") == "application/json"

    def test_unknown_extension_falls_back_to_octet_stream(self) -> None:
        assert guess_media_type("file.bin") == "application/octet-stream"


class TestGitConnectorDiscover:
    def test_discovers_all_tracked_files(self, golden_git_repo: Path) -> None:
        connector = GitConnector(golden_git_repo, region="us")
        refs = list(connector.discover(ConnectorScope(region="us", domain="claims")))
        paths = {ref.metadata["path"] for ref in refs}
        assert paths == {
            "claims-us/openapi.yaml",
            "claims-uk/openapi.yaml",
            "claims-eu/openapi.yaml",
            "off-domain/cafeteria-menu.yaml",
        }

    def test_refs_carry_real_commit_sha(self, golden_git_repo: Path) -> None:
        expected_sha = subprocess.run(
            ["git", "-C", str(golden_git_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        connector = GitConnector(golden_git_repo, region="us")
        refs = list(connector.discover(ConnectorScope(region="us", domain="claims")))
        assert all(ref.metadata["commit"] == expected_sha for ref in refs)
        assert len(expected_sha) == 40  # a real git SHA-1 hex digest

    def test_uri_and_media_type(self, golden_git_repo: Path) -> None:
        connector = GitConnector(golden_git_repo, region="us")
        refs = {ref.metadata["path"]: ref for ref in connector.discover(ConnectorScope(region="us", domain="claims"))}
        ref = refs["claims-us/openapi.yaml"]
        assert ref.uri == f"git://{golden_git_repo.name}/claims-us/openapi.yaml"
        assert ref.media_type == "application/yaml"
        assert ref.system == "git"
        assert ref.region == "us"


class TestGitConnectorFetch:
    def test_fetch_matches_file_on_disk(self, golden_git_repo: Path) -> None:
        connector = GitConnector(golden_git_repo, region="us")
        refs = {ref.metadata["path"]: ref for ref in connector.discover(ConnectorScope(region="us", domain="claims"))}
        ref = refs["claims-us/openapi.yaml"]
        raw = connector.fetch(ref)
        on_disk = (golden_git_repo / "claims-us" / "openapi.yaml").read_bytes()
        assert raw.content == on_disk
        assert raw.version == ref.metadata["commit"]
        assert raw.media_type == "application/yaml"

    def test_fetch_pinned_to_old_commit_does_not_see_later_change(self, golden_git_repo: Path) -> None:
        connector = GitConnector(golden_git_repo, region="us")
        old_refs = {ref.metadata["path"]: ref for ref in connector.discover(ConnectorScope(region="us", domain="claims"))}
        old_ref = old_refs["claims-us/openapi.yaml"]
        old_content = connector.fetch(old_ref).content

        target = golden_git_repo / "claims-us" / "openapi.yaml"
        target.write_text(target.read_text() + "\n# changed after the pin\n")
        subprocess.run(["git", "-C", str(golden_git_repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(golden_git_repo), "commit", "-q", "-m", "second commit"],
            check=True, capture_output=True,
        )

        # Fetching the SAME (old) ref must still return the OLD content -
        # this is what "MUST NOT resolve a moving reference" means.
        still_old_content = connector.fetch(old_ref).content
        assert still_old_content == old_content

        new_refs = {ref.metadata["path"]: ref for ref in connector.discover(ConnectorScope(region="us", domain="claims"))}
        new_ref = new_refs["claims-us/openapi.yaml"]
        assert new_ref.metadata["commit"] != old_ref.metadata["commit"]
        assert connector.fetch(new_ref).content != old_content


class TestGitConnectorHealth:
    def test_ok_for_real_repo(self, golden_git_repo: Path) -> None:
        connector = GitConnector(golden_git_repo, region="us")
        status = connector.health()
        assert status.ok is True
        assert status.system == "git"

    def test_not_ok_for_missing_path(self, tmp_path: Path) -> None:
        connector = GitConnector(tmp_path / "does-not-exist", region="us")
        status = connector.health()
        assert status.ok is False
        assert status.detail != ""
