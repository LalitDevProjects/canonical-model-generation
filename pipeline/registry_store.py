"""
File-based persistence for Section 12.3's Registry API - signed
ReleaseManifests per domain+semver, plus the raw artefact bytes a release
references. Mirrors pipeline/run_store.py's own established convention
(directory-per-key, one JSON document per artefact, base_path resolved
against the repo root unless absolute) rather than inventing a new
storage idiom. Not a general registry service - just enough to write and
re-read what emit/release.py::build_release_manifest already produces.

Releases are ordered by signed_at (ISO 8601, sorts lexically in order)
for GET /v1/registry/{domain}/releases's own listing - the natural,
already-real field, rather than a separate invented sequence counter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from emit.release import ArtefactEntry, ReleaseManifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class RegistryStore:
    """Local-filesystem persistence rooted at base_path (default:
    registry-store/ resolved against the repository root). Pass
    base_path=tmp_path in tests, matching RunStore's own convention."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        candidate = Path(base_path) if base_path is not None else Path("registry-store")
        self._base_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    def release_dir(self, domain: str, semver: str) -> Path:
        return self._base_path / domain / "releases" / semver

    def write_release(self, domain: str, manifest: ReleaseManifest) -> Path:
        release_dir = self.release_dir(domain, manifest.version)
        release_dir.mkdir(parents=True, exist_ok=True)
        destination = release_dir / "manifest.json"
        destination.write_text(
            json.dumps(manifest.to_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        return destination

    def read_release(self, domain: str, semver: str) -> ReleaseManifest:
        path = self.release_dir(domain, semver) / "manifest.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _manifest_from_dict(raw)

    def list_releases(self, domain: str) -> list[ReleaseManifest]:
        """Every release for a domain, ordered by signed_at ascending."""
        releases_dir = self._base_path / domain / "releases"
        if not releases_dir.exists():
            return []
        manifests: list[ReleaseManifest] = []
        for entry in sorted(releases_dir.iterdir()):
            manifest_path = entry / "manifest.json"
            if manifest_path.exists():
                manifests.append(_manifest_from_dict(json.loads(manifest_path.read_text(encoding="utf-8"))))
        manifests.sort(key=lambda m: m.signed_at)
        return manifests

    def write_artefact(self, domain: str, semver: str, path: str, content: bytes, media_type: str) -> Path:
        destination = self.release_dir(domain, semver) / "artefacts" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        _media_type_path(destination).write_text(media_type, encoding="utf-8")
        return destination

    def read_artefact(self, domain: str, semver: str, path: str) -> tuple[bytes, str]:
        destination = self.release_dir(domain, semver) / "artefacts" / path
        content = destination.read_bytes()
        media_type_path = _media_type_path(destination)
        media_type = media_type_path.read_text(encoding="utf-8") if media_type_path.exists() else "application/octet-stream"
        return content, media_type


def _media_type_path(artefact_path: Path) -> Path:
    return artefact_path.with_name(artefact_path.name + ".media-type")


def _manifest_from_dict(raw: dict[str, Any]) -> ReleaseManifest:
    artefacts_raw: list[dict[str, Any]] = raw.get("artefacts") or []
    return ReleaseManifest(
        domain=str(raw["domain"]),
        version=str(raw["version"]),
        run_id=str(raw["runId"]),
        corpus_hash=str(raw["corpusHash"]),
        pins=dict(raw["pins"]),
        artefacts=[ArtefactEntry(path=a["path"], sha256=a["sha256"]) for a in artefacts_raw],
        coverage=dict(raw["coverage"]),
        conformance=dict(raw["conformance"]),
        signed_at=str(raw["signedAt"]),
        decisions=list(raw.get("decisions") or []),
        approvers=list(raw.get("approvers") or []),
        signature=str(raw.get("signature", "")),
    )
