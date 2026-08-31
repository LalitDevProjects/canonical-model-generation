from __future__ import annotations

from uuid import uuid4

from golden_helpers import golden_git, make_source_artefact

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from parsers.openapi import parse_openapi

RUN_ID = uuid4()


def _parse_claims_us() -> dict[str, C5Attributerecord]:
    content = golden_git("claims-us/openapi.yaml")
    source_artefact = make_source_artefact("application/yaml", region="us")
    records = parse_openapi(content, source_artefact, RUN_ID)
    return {r.localName: r for r in records if r.path.startswith("Claim.")}


class TestParseOpenapiClaimSchema:
    """The Claim schema worked example from the plan: golden/git/claims-us/
    openapi.yaml's five fields, proving the type-normalisation boundary
    (reserveAmount -> decimal, never a float type; lossDate stays string
    at the parser level - promoting it is exclusively the profiler's job)."""

    def test_all_five_fields_present(self) -> None:
        by_name = _parse_claims_us()
        assert set(by_name) == {"claimId", "lossDate", "claimant", "reserveAmount", "status"}

    def test_reserve_amount_normalises_to_decimal_never_float(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["reserveAmount"].dataType == "decimal"

    def test_loss_date_stays_string_at_parser_level(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["lossDate"].dataType == "string"

    def test_required_fields_are_mandatory_optional_field_is_not(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["claimId"].obligation.level == "mandatory"
        assert by_name["lossDate"].obligation.level == "mandatory"
        assert by_name["claimant"].obligation.level == "mandatory"
        assert by_name["status"].obligation.level == "mandatory"
        assert by_name["reserveAmount"].obligation.level == "optional"

    def test_required_fields_are_1_1_optional_is_0_1(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["claimId"].cardinality == "1..1"
        assert by_name["reserveAmount"].cardinality == "0..1"

    def test_status_enum_recorded_as_declared(self) -> None:
        by_name = _parse_claims_us()
        status = by_name["status"]
        assert status.enumeration is not None
        values = {item.value for item in status.enumeration}
        assert values == {"OPEN", "CLOSED"}
        assert all(item.source == "declared" for item in status.enumeration)

    def test_descriptions_captured_as_semantics(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["claimId"].semantics is not None
        assert by_name["claimId"].semantics.description == "Unique claim identifier."

    def test_paths_are_dot_delimited_under_claim(self) -> None:
        by_name = _parse_claims_us()
        assert by_name["claimId"].path == "Claim.claimId"
        assert by_name["claimId"].localName == "claimId"

    def test_identity_and_evidence_conventions(self) -> None:
        by_name = _parse_claims_us()
        rec = by_name["claimId"]
        assert rec.attributeId == "attr://us/test-artefact/Claim.claimId"
        assert rec.inferred is False
        assert rec.evidenceTier == 1
        assert len(rec.evidenceRefs) == 1
        evidence_ref = rec.evidenceRefs[0].root
        assert evidence_ref.startswith("evref://us/git/test-artefact@")
        assert "#/components/schemas/Claim/properties/claimId" in evidence_ref


class TestParseOpenapiPathParameter:
    def test_path_parameter_is_extracted(self) -> None:
        content = golden_git("claims-us/openapi.yaml")
        source_artefact = make_source_artefact("application/yaml", region="us")
        records = parse_openapi(content, source_artefact, RUN_ID)
        param_records = [r for r in records if r.path == "getClaim.claimId"]
        assert len(param_records) == 1
        assert param_records[0].obligation.level == "mandatory"
        assert param_records[0].dataType == "string"

    def test_non_http_method_siblings_of_a_path_item_are_skipped(self) -> None:
        # A path item can carry a "parameters" key shared across all its
        # operations, and other non-verb siblings - these must not be
        # mistaken for an HTTP method/operation.
        content = _dump_yaml({
            "paths": {
                "/claims/{claimId}": {
                    "parameters": [{"name": "claimId", "in": "path", "schema": {"type": "string"}}],
                    "get": {
                        "operationId": "getClaim",
                        "parameters": [{"name": "claimId", "in": "path", "required": True, "schema": {"type": "string"}}],
                        "responses": {},
                    },
                },
            },
        })
        source_artefact = make_source_artefact("application/yaml", region="us")
        records = parse_openapi(content, source_artefact, RUN_ID)
        assert [r.path for r in records] == ["getClaim.claimId"]

    def test_parameter_without_schema_is_skipped(self) -> None:
        content = _dump_yaml({
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "getX",
                        "parameters": [{"name": "noSchema", "in": "query"}],
                        "responses": {},
                    },
                },
            },
        })
        source_artefact = make_source_artefact("application/yaml", region="us")
        records = parse_openapi(content, source_artefact, RUN_ID)
        assert records == []


def _dump_yaml(document: dict[str, object]) -> bytes:
    import yaml

    return yaml.safe_dump(document).encode()


def _parse_inline(document: dict[str, object]) -> list[C5Attributerecord]:
    source_artefact = make_source_artefact("application/yaml", region="us")
    return parse_openapi(_dump_yaml(document), source_artefact, RUN_ID)


class TestParseOpenapiRef:
    def test_ref_property_becomes_a_reference_record(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "properties": {"party": {"$ref": "#/components/schemas/Party"}},
                },
                "Party": {"type": "object", "properties": {"name": {"type": "string"}}},
            }},
        })
        party_ref = next(r for r in records if r.path == "Claim.party")
        assert party_ref.dataType == "reference"
        assert party_ref.typeDetail is not None
        assert party_ref.typeDetail.refTarget == "#/components/schemas/Party"
        # $ref is not itself resolved/inlined - "Party" is a separate
        # top-level schema entry and gets its own walk.
        assert any(r.path == "Party.name" for r in records)


class TestParseOpenapiNestedObject:
    def test_nested_object_property_recurses(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "required": ["claimant"],
                    "properties": {
                        "claimant": {
                            "type": "object",
                            "properties": {"fullName": {"type": "string"}},
                        },
                    },
                },
            }},
        })
        self_record = next(r for r in records if r.path == "Claim.claimant")
        assert self_record.dataType == "object"
        assert self_record.obligation.level == "mandatory"
        nested = next(r for r in records if r.path == "Claim.claimant.fullName")
        assert nested.parentPath == "Claim.claimant"


class TestParseOpenapiArray:
    def test_array_of_scalars_gets_array_cardinality(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "required": ["tags"],
                    "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                },
            }},
        })
        rec = next(r for r in records if r.path == "Claim.tags")
        assert rec.dataType == "string"
        assert rec.cardinality == "1..n"

    def test_optional_array_gets_0_n_cardinality(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                },
            }},
        })
        rec = next(r for r in records if r.path == "Claim.tags")
        assert rec.cardinality == "0..n"

    def test_array_of_objects_recurses_into_items(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "properties": {
                        "parties": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                            },
                        },
                    },
                },
            }},
        })
        assert any(r.path == "Claim.parties.name" for r in records)


class TestParseOpenapiConstraints:
    def test_length_pattern_and_range_constraints_are_captured(self) -> None:
        records = _parse_inline({
            "components": {"schemas": {
                "Claim": {
                    "type": "object",
                    "properties": {
                        "claimId": {"type": "string", "minLength": 1, "maxLength": 20, "pattern": "^C[0-9]+$"},
                        "reserveAmount": {"type": "number", "minimum": 0, "maximum": 1000000},
                    },
                },
            }},
        })
        claim_id = next(r for r in records if r.path == "Claim.claimId")
        assert claim_id.constraints is not None
        kinds = {c.kind for c in claim_id.constraints}
        assert kinds == {"length", "pattern"}

        reserve_amount = next(r for r in records if r.path == "Claim.reserveAmount")
        assert reserve_amount.constraints is not None
        assert {c.kind for c in reserve_amount.constraints} == {"range"}
