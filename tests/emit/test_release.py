"""Hermetic tests for emit/release.py - the release manifest builder and
its hand-written schema (not a C-numbered contract)."""

from __future__ import annotations

import hashlib

import pytest
from jsonschema import Draft202012Validator, ValidationError

from emit.release import RELEASE_MANIFEST_SCHEMA, build_release_manifest, validate_release_manifest

pytestmark = pytest.mark.unit


def _build(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = dict(
        domain="claims", version="1.0.0", run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44",
        corpus_hash="sha256:abc", pins={}, artefacts=[("Claim.json", b'{"a":1}')],
        coverage_score=0.95, gate1=True, gate2=True, gate3=True, acord_conformance=0.0,
        signature="sig:placeholder",
    )
    payload.update(overrides)
    manifest = build_release_manifest(**payload)  # type: ignore[arg-type]
    return manifest.to_dict()


def test_schema_is_a_valid_meta_schema() -> None:
    Draft202012Validator.check_schema(RELEASE_MANIFEST_SCHEMA)


def test_signed_at_defaults_to_a_real_timestamp() -> None:
    d = _build()
    assert isinstance(d["signedAt"], str) and d["signedAt"]


def test_signed_at_override_is_used_verbatim() -> None:
    d = _build(signed_at="2026-09-30T14:05:00+00:00")
    assert d["signedAt"] == "2026-09-30T14:05:00+00:00"


def test_artefact_hash_is_real_sha256_of_content() -> None:
    d = _build()
    expected = hashlib.sha256(b'{"a":1}').hexdigest()
    assert d["artefacts"] == [{"path": "Claim.json", "sha256": expected}]


def test_coverage_and_conformance_shape() -> None:
    d = _build()
    assert d["coverage"] == {"score": 0.95, "gate1": True, "gate2": True, "gate3": True}
    assert d["conformance"] == {"acord": 0.0}


def test_decisions_and_approvers_default_empty() -> None:
    d = _build()
    assert d["decisions"] == []
    assert d["approvers"] == []


def test_valid_manifest_passes_validation() -> None:
    validate_release_manifest(_build())


def test_missing_required_field_fails_validation() -> None:
    d = _build()
    del d["signature"]
    with pytest.raises(ValidationError):
        validate_release_manifest(d)


def test_extra_field_fails_validation() -> None:
    d = _build()
    d["unexpectedField"] = "x"
    with pytest.raises(ValidationError):
        validate_release_manifest(d)
