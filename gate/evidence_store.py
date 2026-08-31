"""
The evidence store (Section 3.7): "evidence-store/artefacts/{sha256[0:2]}/{sha256}
# content-addressed, immutable." Retention rationale (Section 3.6):
"Audit trail for released models; aligned to the DPIA outcome and the
syndicate's record-retention policy" - 7 years, unlike run-store's 24
months.

A minimal writer only - Increment 4's own scope (a confirmed builder
decision: build this now, rather than leaving it to Increment 5, since
the gate is the first stage that has real redacted content worth writing
here at all). Called once per admitted artefact, right after redaction,
so `evidence-store/` holds exactly what actually crossed the gate - the
content contentHash is computed over.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class EvidenceStore:
    """Local-filesystem persistence rooted at base_path (default:
    evidence-store/ resolved against the repository root). Pass
    base_path=tmp_path in tests so no test run ever touches a real
    evidence-store/ directory."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        candidate = Path(base_path) if base_path is not None else Path("evidence-store")
        self._base_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    def _artefact_path(self, content_hash: str) -> Path:
        return self._base_path / "artefacts" / content_hash[:2] / content_hash

    def write_artefact(self, content_hash: str, content: bytes) -> Path:
        """Content-addressed and idempotent: writing the same
        content_hash twice is a no-op on the second call (matching
        Section 3.5's "ingest-svc ... Stateless; idempotent on content
        hash" framing), not an error - the bytes at a given hash never
        change."""
        path = self._artefact_path(content_hash)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return path

    def read_artefact(self, content_hash: str) -> bytes:
        return self._artefact_path(content_hash).read_bytes()

    def has_artefact(self, content_hash: str) -> bool:
        return self._artefact_path(content_hash).exists()
