"""Hermetic tests for emit/schema.py and emit/common_schemas.py - schema
validity via Draft202012Validator.check_schema(), determinism via
two-run byte comparison."""

from __future__ import annotations

import pytest
from emit_builders import candidate
from jsonschema import Draft202012Validator

from emit.common_schemas import build_common_schemas
from emit.schema import build_entity_schemas, build_extension_schemas, serialise

pytestmark = pytest.mark.unit


class TestCommonSchemas:
    def test_all_six_common_types_present(self) -> None:
        schemas = build_common_schemas("claims", "1.0")
        assert set(schemas) == {"Party", "PostalAddress", "MonetaryAmount", "ContactPoint", "DocumentRef", "Identifier"}

    def test_every_common_schema_is_a_valid_meta_schema(self) -> None:
        for schema in build_common_schemas("claims", "1.0").values():
            Draft202012Validator.check_schema(schema)

    def test_monetary_amount_matches_to_monetary_amount_output_shape(self) -> None:
        schema = build_common_schemas("claims", "1.0")["MonetaryAmount"]
        assert set(schema["properties"]) == {"amount", "currency"}

    def test_identifier_matches_to_identifier_output_shape(self) -> None:
        schema = build_common_schemas("claims", "1.0")["Identifier"]
        assert set(schema["properties"]) == {"value", "scheme", "issuer"}


class TestBuildEntitySchemas:
    def test_core_attribute_becomes_a_required_property(self) -> None:
        schemas = build_entity_schemas([candidate(placement="core", obligation="mandatory")], domain="claims", version="1.0")
        claim = schemas["Claim"]
        assert claim["required"] == ["claimId"]
        assert claim["properties"]["claimId"]["type"] == "string"

    def test_optional_attribute_is_not_required(self) -> None:
        schemas = build_entity_schemas([candidate(placement="core", obligation="optional")], domain="claims", version="1.0")
        assert "required" not in schemas["Claim"]

    def test_extension_attribute_is_not_inlined_only_referenced(self) -> None:
        schemas = build_entity_schemas(
            [candidate(placement="core"), candidate(attribute="mojRef", placement="extension:uk")],
            domain="claims", version="1.0",
        )
        claim = schemas["Claim"]
        assert "mojRef" not in claim["properties"]
        assert claim["properties"]["extensions"]["properties"]["uk"] == {"$ref": "./extensions/uk/ClaimExtension.json"}

    def test_entity_with_only_extension_attributes_still_gets_a_schema(self) -> None:
        schemas = build_entity_schemas([candidate(placement="extension:uk")], domain="claims", version="1.0")
        assert "Claim" in schemas
        assert schemas["Claim"]["properties"] == {
            "extensions": {"type": "object", "additionalProperties": False, "properties": {"uk": {"$ref": "./extensions/uk/ClaimExtension.json"}}}
        }

    def test_description_ends_with_canonical_attribute_identifier(self) -> None:
        schemas = build_entity_schemas([candidate()], domain="claims", version="1.0")
        description = schemas["Claim"]["properties"]["claimId"]["description"]
        assert description.endswith("canon://Claim.claimId")

    def test_evidence_is_attached_when_provided(self) -> None:
        schemas = build_entity_schemas(
            [candidate()], domain="claims", version="1.0",
            evidence_by_candidate={"canon://Claim.claimId": ["evref://uk/git/x@" + "a" * 16 + "#/y"]},
        )
        assert schemas["Claim"]["properties"]["claimId"]["x-evidence"] == ["evref://uk/git/x@" + "a" * 16 + "#/y"]

    def test_every_emitted_entity_schema_is_a_valid_meta_schema(self) -> None:
        schemas = build_entity_schemas([candidate(placement="core"), candidate(attribute="mojRef", placement="extension:uk")], domain="claims", version="1.0")
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)


class TestBuildExtensionSchemas:
    def test_one_schema_per_region_entity_pair(self) -> None:
        schemas = build_extension_schemas([candidate(attribute="mojRef", placement="extension:uk")], domain="claims", version="1.0")
        assert set(schemas) == {("uk", "Claim")}

    def test_owner_default_when_not_provided(self) -> None:
        schemas = build_extension_schemas([candidate(attribute="mojRef", placement="extension:uk")], domain="claims", version="1.0")
        assert schemas[("uk", "Claim")]["x-owner"] == "Regional Architect, UK"

    def test_owner_override_is_used(self) -> None:
        schemas = build_extension_schemas(
            [candidate(attribute="mojRef", placement="extension:uk")], domain="claims", version="1.0",
            owners={"uk": "Jane Doe"},
        )
        assert schemas[("uk", "Claim")]["x-owner"] == "Jane Doe"

    def test_property_carries_placement_rule_and_weight(self) -> None:
        schemas = build_extension_schemas([candidate(attribute="mojRef", placement="extension:uk", weight=3)], domain="claims", version="1.0")
        prop = schemas[("uk", "Claim")]["properties"]["mojRef"]
        assert prop["x-placementRule"] == "4"
        assert prop["x-weight"] == 3

    def test_core_candidates_never_produce_an_extension_schema(self) -> None:
        schemas = build_extension_schemas([candidate(placement="core")], domain="claims", version="1.0")
        assert schemas == {}

    def test_every_emitted_extension_schema_is_a_valid_meta_schema(self) -> None:
        schemas = build_extension_schemas([candidate(attribute="mojRef", placement="extension:uk", obligation="mandatory")], domain="claims", version="1.0")
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
        assert schemas[("uk", "Claim")]["required"] == ["mojRef"]


class TestSerialise:
    def test_two_runs_are_byte_identical(self) -> None:
        doc = {"b": 1, "a": 2}
        assert serialise(doc) == serialise(doc)

    def test_sorted_keys_and_lf_ending(self) -> None:
        content = serialise({"b": 1, "a": 2})
        text = content.decode("utf-8")
        assert text.index('"a"') < text.index('"b"')
        assert content.endswith(b"\n")
        assert b"\r" not in content

    def test_serialises_a_list_too(self) -> None:
        content = serialise([{"x": 1}])
        assert content.decode("utf-8").startswith("[")
