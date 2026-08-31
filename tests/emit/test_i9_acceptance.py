"""
Increment 9's own literal acceptance test (Section 17.2's PoC Build Guide
row): "Emitted schemas validate; every round-trip test passes or its loss
is declared; the pack is complete enough to run a real session from."

Zero LLM, zero DB dependency - the deterministic pipeline alone (mapping
compiler/interpreter/round-trip generator + emit/'s schema/OpenAPI/
logical-model/release-manifest/workshop-pack builders) satisfies all
three clauses, the same "deterministic pipeline alone satisfies the
acceptance test" precedent I7/I8's own acceptance tests already
established.

Fixtures: golden/mapping/{region_attributes,uk-claims-v3.mapping}.json -
region_attributes.json is a real C5 AttributeRecord list for the exact 7
region paths Appendix C's own worked mapping spec covers (one flattened
from its own array-shaped `coveragesInForce[].limit` path - see that
mapping file's own note - mapping/interpreter.py's reference interpreter
does not resolve `[]` path segments). golden/coverage/{candidates,
clusters}.json (Increment 8's own golden data) are reused directly for
the emission side, rather than duplicating a parallel candidate/cluster
fixture set.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C9.GapEntry._1_0 import C9Gapentry
from generated.C10.MappingSpec._1_0 import C10Mappingspec

from emit.openapi import build_openapi_projection
from emit.release import build_release_manifest
from emit.schema import build_entity_schemas, build_extension_schemas, serialise
from emit.workshop_pack import assemble_pack
from mapping.compiler import compile_spec
from mapping.roundtrip import generate_round_trip_tests, summarise

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GOLDEN_MAPPING = _REPO_ROOT / "golden" / "mapping"
_GOLDEN_COVERAGE = _REPO_ROOT / "golden" / "coverage"

_CANONICAL_TYPES = {
    "claimReference": "Identifier",
    "incident.occurrenceDateTime": "dateTime",
    "claimStatus": "string",
    "coverageLimit": "MonetaryAmount",
    "extensions.uk.mojPortalReference": "string",
}


def _region_ir() -> list[C5Attributerecord]:
    raw = json.loads((_GOLDEN_MAPPING / "region_attributes.json").read_text(encoding="utf-8"))
    return [C5Attributerecord.model_validate(r) for r in raw]


def _mapping_spec() -> C10Mappingspec:
    raw = json.loads((_GOLDEN_MAPPING / "uk-claims-v3.mapping.json").read_text(encoding="utf-8"))
    return C10Mappingspec.model_validate(raw)


def _candidates() -> list[C8Canonicalcandidate]:
    raw = json.loads((_GOLDEN_COVERAGE / "candidates.json").read_text(encoding="utf-8"))
    return [C8Canonicalcandidate.model_validate(c) for c in raw]


def _clusters() -> list[C6Conceptcluster]:
    raw = json.loads((_GOLDEN_COVERAGE / "clusters.json").read_text(encoding="utf-8"))
    return [C6Conceptcluster.model_validate(c) for c in raw]


class TestClauseOneEmittedSchemasValidate:
    def test_every_entity_and_extension_schema_is_a_valid_meta_schema(self) -> None:
        candidates = _candidates()
        entity_schemas = build_entity_schemas(candidates, domain="claims", version="1.0")
        extension_schemas = build_extension_schemas(candidates, domain="claims", version="1.0")
        assert entity_schemas, "golden candidates must produce at least one entity schema"
        for schema in {**entity_schemas, **{f"{r}/{e}": s for (r, e), s in extension_schemas.items()}}.values():
            Draft202012Validator.check_schema(schema)

    def test_a_real_candidate_instance_validates_against_its_own_emitted_schema(self) -> None:
        candidates = _candidates()
        entity_schemas = build_entity_schemas(candidates, domain="claims", version="1.0")
        instance = {"claimId": "CLM-000123"}
        Draft202012Validator(entity_schemas["Claim"]).validate(instance)

    def test_openapi_projection_references_only_real_emitted_entity_schemas(self) -> None:
        candidates = _candidates()
        entity_schemas = build_entity_schemas(candidates, domain="claims", version="1.0")
        paths = {entity: f"{entity}.json" for entity in entity_schemas}
        doc = build_openapi_projection(domain="claims", version="1.0", entity_schema_paths=paths)
        assert set(doc["components"]["schemas"]) == set(entity_schemas)
        for entity, ref in doc["components"]["schemas"].items():
            assert ref == {"$ref": paths[entity]}


class TestClauseTwoRoundTripPassesOrLossDeclared:
    def test_golden_mapping_spec_compiles_and_round_trips_clean(self) -> None:
        plan = compile_spec(_mapping_spec(), _region_ir(), canonical_types=_CANONICAL_TYPES)
        cases = generate_round_trip_tests(plan, _region_ir(), n=24)
        assert not any(case.undeclared_losses for case in cases)

    def test_summary_matches_appendix_c_shape_one_declared_precision_loss(self) -> None:
        plan = compile_spec(_mapping_spec(), _region_ir(), canonical_types=_CANONICAL_TYPES)
        cases = generate_round_trip_tests(plan, _region_ir(), n=24)
        summary = summarise(cases, plan)
        assert summary["result"] == "pass"
        assert summary["generated"] == 24
        assert [loss["path"] for loss in summary["declaredLosses"]] == ["ClaimHeader.LossDate"]
        assert summary["declaredLosses"][0]["kind"] == "precision"


class TestClauseThreeWorkshopPackComplete:
    def test_assembled_pack_is_complete_and_internally_consistent(self, tmp_path: Path) -> None:
        candidates = _candidates()
        clusters = _clusters()
        plan = compile_spec(_mapping_spec(), _region_ir(), canonical_types=_CANONICAL_TYPES)
        cases = generate_round_trip_tests(plan, _region_ir(), n=24)
        round_trip_summary = summarise(cases, plan)

        coverage_report = C9Coveragereport.model_validate({
            "domain": "claims", "score": 0.95, "denominator": 2, "weightSum": 8.0,
            "perRegion": {"us": 1.0, "uk": 0.9, "eu": 0.85},
            "gate1Pass": True, "gate2Pass": True, "gate3Pass": False,
            "specifiedVsInferred": {"specified": 2, "inferred": 0}, "exclusions": [],
        })
        gap_register = [
            C9Gapentry.model_validate({
                "conceptId": "canon://Claim.reserveAmount", "weight": 3, "reason": "unevidenced",
                "affectedRegions": ["us"],
            })
        ]
        artefact_bytes = serialise(round_trip_summary)
        release_manifest = build_release_manifest(
            domain="claims", version="1.0.0", run_id="b0f2e7c4-9a11-4d2e-8f30-6c5b7d1e2a44",
            corpus_hash="sha256:9f2c8ab41d77e0356c1fbb2093ea5d18e41b", pins={},
            artefacts=[("mappings/uk-claims-v3.mapping.json", artefact_bytes)],
            coverage_score=0.95, gate1=True, gate2=True, gate3=False, acord_conformance=0.0,
            signature="sig:placeholder",
        )

        manifest = assemble_pack(
            tmp_path, domain="claims", version="1.0",
            candidates=candidates, clusters=clusters,
            mapping_specs={"uk-claims-v3": _mapping_spec()},
            round_trip_summaries={"uk-claims-v3": round_trip_summary},
            coverage_report=coverage_report, gap_register=gap_register,
            release_manifest=release_manifest,
        )

        # Every manifest entry is a real file on disk with a matching hash.
        for entry in manifest.files:
            content = (tmp_path / entry.path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == entry.sha256

        paths = {f.path for f in manifest.files}
        assert "Claim.json" in paths
        assert "extensions/us/ClaimExtension.json" in paths
        assert "mappings/uk-claims-v3.mapping.json" in paths
        assert "mappings/uk-claims-v3.mapping.yaml" in paths
        assert "coverage-report.json" in paths
        assert "gap-register.json" in paths
        assert "release-manifest.json" in paths
        assert "acord-alignment.md" in paths
        assert (tmp_path / "release-manifest.json").exists()

        # The pack's own declared-loss roll-up surfaces the one real
        # declared loss an SME needs to see before approving the release.
        assert manifest.declared_losses == [
            {"mappingSpec": "uk-claims-v3", "path": "ClaimHeader.LossDate", "kind": "precision",
             "detail": round_trip_summary["declaredLosses"][0]["detail"]}
        ]
