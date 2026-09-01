"""
Section 11.4's release manifest, the worked JSON example transcribed as a
real, hand-written schema (emit/schemas/release_manifest.schema.json) -
NOT a 12th C-numbered contract (see that schema's own description, and
docs/contracts.md's "Known design gaps" section).

`signature` is a caller-supplied string, not computed here: no real
signing infrastructure (sigstore or otherwise) exists in this repo, the
same PoC-placeholder status `config/settings.py::EgressConfig.
ledger_signing_key` already carries for its own HMAC key material -
inventing a new signing mechanism for one field would be scope creep
this increment's own acceptance test does not require.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "release_manifest.schema.json"
RELEASE_MANIFEST_SCHEMA: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ArtefactEntry:
    path: str
    sha256: str


@dataclass(frozen=True)
class ReleaseManifest:
    domain: str
    version: str
    run_id: str
    corpus_hash: str
    pins: dict[str, Any]
    artefacts: list[ArtefactEntry]
    coverage: dict[str, Any]
    conformance: dict[str, Any]
    signed_at: str
    decisions: list[dict[str, Any]] = field(default_factory=list)
    approvers: list[dict[str, Any]] = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "version": self.version,
            "runId": self.run_id,
            "corpusHash": self.corpus_hash,
            "pins": self.pins,
            "artefacts": [{"path": a.path, "sha256": a.sha256} for a in self.artefacts],
            "coverage": self.coverage,
            "conformance": self.conformance,
            "signedAt": self.signed_at,
            "decisions": self.decisions,
            "approvers": self.approvers,
            "signature": self.signature,
        }


def _sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_release_manifest(
    *,
    domain: str,
    version: str,
    run_id: str,
    corpus_hash: str,
    pins: dict[str, Any],
    artefacts: Sequence[tuple[str, bytes]],
    coverage_score: float,
    gate1: bool,
    gate2: bool,
    gate3: bool,
    acord_conformance: float,
    signed_at: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    approvers: list[dict[str, Any]] | None = None,
    signature: str = "",
) -> ReleaseManifest:
    """`artefacts` is (relative_path, content_bytes) pairs - the caller
    already has the serialised bytes in hand (emit/schema.py::serialise
    et al.), so hashing here never re-reads from disk. `signed_at`
    defaults to now (UTC, ISO 8601) - Section 12.3's own GET .../releases
    response shape names this field even though Section 11.4's worked
    example never included it (see the schema's own description)."""
    return ReleaseManifest(
        domain=domain,
        version=version,
        run_id=run_id,
        corpus_hash=corpus_hash,
        pins=pins,
        artefacts=[ArtefactEntry(path=path, sha256=_sha256_of(content)) for path, content in artefacts],
        coverage={"score": coverage_score, "gate1": gate1, "gate2": gate2, "gate3": gate3},
        conformance={"acord": acord_conformance},
        signed_at=signed_at or datetime.now(timezone.utc).isoformat(),
        decisions=decisions or [],
        approvers=approvers or [],
        signature=signature,
    )


def validate_release_manifest(manifest: dict[str, Any]) -> None:
    """Raises jsonschema.ValidationError on a malformed manifest -
    mirrors agents/validation.py::validate_schema's direct-validator
    pattern rather than routing through a generated Pydantic model (there
    is none; this is not a codegen'd contract)."""
    Draft202012Validator(RELEASE_MANIFEST_SCHEMA).validate(manifest)
