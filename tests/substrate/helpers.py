"""Shared C1Sourceartefact test-builder - not a pytest conftest.py (no
fixtures here), named to avoid the module-name collision mypy hit at
Increment 3 between two conftest.py files (see tests/parsers/golden_helpers.py)."""

from __future__ import annotations

import hashlib

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact


def make_artefact(
    *,
    artefact_id: str = "art-1",
    region: str = "uk",
    system: str = "git",
    content: bytes,
    media_type: str,
    evidence_tier: int = 1,
) -> C1Sourceartefact:
    """content_hash is the real sha256 of the given content - matching
    the mask-then-hash convention every real C1Sourceartefact in this
    repo already follows (contracts/validators.py, gate/gate.py)."""
    return C1Sourceartefact.model_validate({
        "artefactId": artefact_id,
        "region": region,
        "system": system,
        "uri": f"golden://{artefact_id}",
        "version": "v1",
        "contentHash": hashlib.sha256(content).hexdigest(),
        "mediaType": media_type,
        "evidenceTier": evidence_tier,
        "sanitisation": {
            "artefactId": artefact_id,
            "contentHash": hashlib.sha256(content).hexdigest(),
            "labels": ["STRUCTURAL"],
            "verdict": "allow",
            "licenceDisposition": "permitted",
            "policyVersion": 3,
            "classifiedAt": "2026-08-31T12:00:00Z",
        },
    })
