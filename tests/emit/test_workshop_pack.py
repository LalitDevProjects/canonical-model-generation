"""Hermetic tests for emit/workshop_pack.py::assemble_pack - directory
assembly, manifest hash integrity, and byte-identical re-runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from emit_builders import alignment, candidate, cluster, coverage_report, gap_entry

from generated.C10.MappingSpec._1_0 import C10Mappingspec
from emit.release import build_release_manifest
from emit.workshop_pack import assemble_pack

pytestmark = pytest.mark.unit

_EVREF = f"evref://uk/git/art-1@{'a' * 16}#/x"


def _mapping_spec() -> C10Mappingspec:
    return C10Mappingspec.model_validate({
        "header": {
            "mappingSpecId": "mapping-uk-claims", "canonicalRef": "canon://claims/1.0", "direction": "toCanonical",
            "generatedFrom": {"run": "b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44", "corpusManifest": "cm-x", "agent": "mapping-generator/1.4.0"},
        },
        "mappings": [
            {
                "canonical": "claimId", "region": "ClaimNo", "transform": "identity", "weight": 5,
                "onFailure": "reject", "evidence": [_EVREF],
            }
        ],
        "valueMaps": {"ClaimStatus.uk": {"mappings": {"NEW": "NOTIFIED"}, "unmappedValues": "escalate"}},
    })


def _release_manifest() -> object:
    return build_release_manifest(
        domain="claims", version="1.0.0", run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44", corpus_hash="sha256:abc",
        pins={}, artefacts=[], coverage_score=0.95, gate1=True, gate2=True, gate3=True, acord_conformance=0.0,
        signature="sig:placeholder",
    )


def _assemble(output_dir: Path, **overrides: object) -> object:
    defaults: dict[str, object] = dict(
        output_dir=output_dir, domain="claims", version="1.0",
        candidates=[candidate()], clusters=[cluster()],
        mapping_specs={"uk-claims": _mapping_spec()},
        round_trip_summaries={"uk-claims": {"generated": 24, "assertion": "x", "declaredLosses": [], "result": "pass"}},
        coverage_report=coverage_report(), gap_register=[gap_entry()],
        release_manifest=_release_manifest(),
    )
    defaults.update(overrides)
    return assemble_pack(**defaults)  # type: ignore[arg-type]


class TestAssemblePack:
    def test_writes_the_expected_file_set(self, tmp_path: Path) -> None:
        manifest = _assemble(tmp_path)
        paths = {f.path for f in manifest.files}  # type: ignore[attr-defined]
        assert "Claim.json" in paths
        assert "openapi.yaml" in paths
        assert "logical-model.jsonld" in paths
        assert "coverage-report.json" in paths
        assert "gap-register.json" in paths
        assert "release-manifest.json" in paths
        assert "acord-alignment.md" in paths
        assert "mappings/uk-claims.mapping.json" in paths
        assert "mappings/uk-claims.mapping.yaml" in paths
        assert "valuemaps/ClaimStatus.uk.yaml" in paths
        for name in ("Party", "PostalAddress", "MonetaryAmount", "ContactPoint", "DocumentRef", "Identifier"):
            assert f"common/{name}.json" in paths

    def test_extension_schema_is_written_for_an_extension_placed_candidate(self, tmp_path: Path) -> None:
        manifest = _assemble(
            tmp_path,
            candidates=[candidate(), candidate(attribute="mojRef", placement="extension:uk")],
        )
        paths = {f.path for f in manifest.files}  # type: ignore[attr-defined]
        assert "extensions/uk/ClaimExtension.json" in paths

    def test_manifest_file_itself_is_written_to_disk(self, tmp_path: Path) -> None:
        _assemble(tmp_path)
        assert (tmp_path / "workshop-pack-manifest.json").is_file()

    def test_every_manifest_entry_hash_matches_the_real_file_on_disk(self, tmp_path: Path) -> None:
        manifest = _assemble(tmp_path)
        for entry in manifest.files:  # type: ignore[attr-defined]
            content = (tmp_path / entry.path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == entry.sha256

    def test_declared_losses_carry_the_originating_mapping_spec_key(self, tmp_path: Path) -> None:
        manifest = _assemble(
            tmp_path,
            round_trip_summaries={
                "uk-claims": {
                    "generated": 24, "assertion": "x",
                    "declaredLosses": [{"path": "x", "kind": "precision", "detail": "d"}],
                    "result": "pass",
                }
            },
        )
        assert manifest.declared_losses == [{"mappingSpec": "uk-claims", "path": "x", "kind": "precision", "detail": "d"}]  # type: ignore[attr-defined]

    def test_acord_manual_section_lists_the_cluster_and_its_verdict(self, tmp_path: Path) -> None:
        _assemble(tmp_path, alignment_by_cluster={"cluster://claim-id": alignment(verdict="unassessed")})
        text = (tmp_path / "acord-alignment.md").read_text(encoding="utf-8")
        assert "cluster://claim-id" in text
        assert "unassessed" in text

    def test_re_running_produces_byte_identical_files(self, tmp_path: Path) -> None:
        manifest1 = _assemble(tmp_path)
        manifest2 = _assemble(tmp_path)
        h1 = {f.path: f.sha256 for f in manifest1.files}  # type: ignore[attr-defined]
        h2 = {f.path: f.sha256 for f in manifest2.files}  # type: ignore[attr-defined]
        assert h1 == h2

    def test_coverage_report_round_trips_real_values(self, tmp_path: Path) -> None:
        _assemble(tmp_path)
        written = json.loads((tmp_path / "coverage-report.json").read_text(encoding="utf-8"))
        assert written["score"] == 0.95
        assert written["gate1Pass"] is True

    def test_gap_register_is_a_json_array(self, tmp_path: Path) -> None:
        _assemble(tmp_path)
        written = json.loads((tmp_path / "gap-register.json").read_text(encoding="utf-8"))
        assert isinstance(written, list)
        assert written[0]["reason"] == "excluded"

    def test_release_manifest_is_schema_valid_on_disk(self, tmp_path: Path) -> None:
        _assemble(tmp_path)
        written = json.loads((tmp_path / "release-manifest.json").read_text(encoding="utf-8"))
        assert written["domain"] == "claims"
        assert written["signature"] == "sig:placeholder"
