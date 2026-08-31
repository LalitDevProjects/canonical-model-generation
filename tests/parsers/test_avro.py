from __future__ import annotations

import json
from uuid import uuid4

from golden_helpers import golden_avro, make_source_artefact

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from parsers.avro import parse_avro

RUN_ID = uuid4()


def _parse_claim_event() -> dict[str, C5Attributerecord]:
    content = golden_avro("us/ClaimEvent.avsc")
    source_artefact = make_source_artefact("application/vnd.apache.avro+json", region="us")
    records = parse_avro(content, source_artefact, RUN_ID)
    return {r.localName: r for r in records}


class TestParseAvroClaimEvent:
    def test_all_fields_present(self) -> None:
        by_name = _parse_claim_event()
        assert set(by_name) == {"claimId", "lossDate", "reserveAmount", "status"}

    def test_reserve_amount_decimal_logical_type(self) -> None:
        by_name = _parse_claim_event()
        assert by_name["reserveAmount"].dataType == "decimal"

    def test_loss_date_date_logical_type(self) -> None:
        by_name = _parse_claim_event()
        assert by_name["lossDate"].dataType == "date"

    def test_plain_string_field(self) -> None:
        by_name = _parse_claim_event()
        assert by_name["claimId"].dataType == "string"

    def test_all_fields_mandatory_1_1(self) -> None:
        by_name = _parse_claim_event()
        for record in by_name.values():
            assert record.obligation.level == "mandatory"
            assert record.cardinality == "1..1"

    def test_doc_string_captured_as_description(self) -> None:
        content = json.dumps({
            "type": "record", "name": "X",
            "fields": [{"name": "y", "type": "string", "doc": "a docstring"}],
        }).encode()
        source_artefact = make_source_artefact("application/vnd.apache.avro+json")
        records = parse_avro(content, source_artefact, RUN_ID)
        assert records[0].semantics is not None
        assert records[0].semantics.description == "a docstring"


class TestParseAvroIdioms:
    def test_nested_record_recurses(self) -> None:
        content = json.dumps({
            "type": "record", "name": "Outer",
            "fields": [
                {"name": "inner", "type": {
                    "type": "record", "name": "Inner",
                    "fields": [{"name": "value", "type": "string"}],
                }},
            ],
        }).encode()
        source_artefact = make_source_artefact("application/vnd.apache.avro+json")
        records = parse_avro(content, source_artefact, RUN_ID)
        paths = {r.path for r in records}
        assert "Outer.inner" in paths
        assert "Outer.inner.value" in paths
        inner_self = next(r for r in records if r.path == "Outer.inner")
        assert inner_self.dataType == "object"

    def test_array_field_gets_0_n_cardinality(self) -> None:
        content = json.dumps({
            "type": "record", "name": "X",
            "fields": [{"name": "tags", "type": {"type": "array", "items": "string"}}],
        }).encode()
        source_artefact = make_source_artefact("application/vnd.apache.avro+json")
        records = parse_avro(content, source_artefact, RUN_ID)
        assert records[0].cardinality == "0..n"
        assert records[0].dataType == "string"

    def test_union_type_normalises_to_unknown(self) -> None:
        content = json.dumps({
            "type": "record", "name": "X",
            "fields": [{"name": "maybeString", "type": ["null", "string"]}],
        }).encode()
        source_artefact = make_source_artefact("application/vnd.apache.avro+json")
        records = parse_avro(content, source_artefact, RUN_ID)
        assert records[0].dataType == "unknown"
