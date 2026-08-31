"""
Git connector (Section 4.1). Pinning strategy: commit SHA, resolved once at
run start ("Commit SHA per repository, resolved once at run start").

Operates on an already-checked-out LOCAL repository path - no remote
clone/fetch. The spec's "shallow clone with --filter=blob:none, then
targeted fetch" describes how a remote-facing git connector obtains a
working copy in the first place; that's out of scope here by design (tests
use a hermetic temporary repository rather than a remote or a repo nested
inside this one - see tests/connectors/conftest.py's golden_git_repo
fixture). A documented simplification, not a spec violation: the fixture
still uses real git plumbing and produces a real commit SHA.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

from connectors.base import ArtefactRef, Connector, ConnectorScope, HealthStatus, RawArtefact

_MEDIA_TYPES = {
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".json": "application/json",
    ".xsd": "application/xml",
    ".wsdl": "application/xml",
    ".xml": "application/xml",
    ".md": "text/markdown",
}


def guess_media_type(path: str) -> str:
    """Extension -> media-type lookup. Output values MUST stay in sync with
    config/platform.yaml's relevance.contract_media_types list, since a
    media type this function produces that isn't in that list scores the
    'kind' relevance signal at 0.3 instead of 1.0."""
    return _MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


class GitConnector(Connector):
    system = "git"

    def __init__(self, repo_path: Path, region: str) -> None:
        self._repo_path = repo_path
        self._region = region

    def discover(self, scope: ConnectorScope) -> Iterator[ArtefactRef]:
        """Cheap: git ls-tree enumerates every tracked path at HEAD without
        reading any blob content."""
        sha = self._run_text(["rev-parse", "HEAD"]).stdout.strip()
        listing = self._run_text(["ls-tree", "-r", "--name-only", "HEAD"]).stdout
        for rel_path in listing.splitlines():
            if not rel_path:
                continue
            yield ArtefactRef(
                uri=f"git://{self._repo_path.name}/{rel_path}",
                system=self.system,
                region=self._region,
                media_type=guess_media_type(rel_path),
                title=Path(rel_path).name,
                metadata={"path": rel_path, "commit": sha},
            )

    def fetch(self, ref: ArtefactRef) -> RawArtefact:
        """Retrieves content at the exact pinned commit via `git show
        {sha}:{path}` - never the working tree, so a later commit on the
        same repo cannot change what an already-issued ArtefactRef fetches."""
        commit = ref.metadata["commit"]
        rel_path = ref.metadata["path"]
        content = self._run_bytes(["show", f"{commit}:{rel_path}"]).stdout
        return RawArtefact(
            uri=ref.uri,
            version=commit,
            content=content,
            media_type=ref.media_type,
            owning_team=None,
            metadata={"path": rel_path},
        )

    def health(self) -> HealthStatus:
        try:
            self._run_text(["rev-parse", "--is-inside-work-tree"])
            return HealthStatus(system=self.system, ok=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            return HealthStatus(system=self.system, ok=False, detail=str(exc))

    def _run_text(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self._repo_path), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    def _run_bytes(self, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self._repo_path), *args],
            capture_output=True,
            text=False,
            check=True,
        )
