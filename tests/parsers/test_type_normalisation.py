from __future__ import annotations

from generated.common.defs import DataType
from parsers.type_normalisation import from_avro, from_openapi, from_xsd_qname


class TestFromOpenapi:
    def test_no_type_declared_is_unknown(self) -> None:
        result = from_openapi(None, None)
        assert result.data_type == DataType.unknown

    def test_plain_number_is_decimal_never_a_float_type(self) -> None:
        # The worked example this increment's acceptance test cares about:
        # golden/git/claims-us/openapi.yaml's reserveAmount: {type: number}.
        result = from_openapi("number", None)
        assert result.data_type == DataType.decimal

    def test_plain_string_stays_string(self) -> None:
        # golden/git/claims-us/openapi.yaml's lossDate: {type: string} -
        # the parser must NOT promote this to date. That's the profiler's job.
        result = from_openapi("string", None)
        assert result.data_type == DataType.string

    def test_date_format_normalises_to_date(self) -> None:
        result = from_openapi("string", "date")
        assert result.data_type == DataType.date

    def test_date_time_format_records_offset_required(self) -> None:
        result = from_openapi("string", "date-time")
        assert result.data_type == DataType.dateTime
        assert result.type_detail["offsetRequired"] is True

    def test_int32_format_records_bits(self) -> None:
        result = from_openapi("integer", "int32")
        assert result.data_type == DataType.integer
        assert result.type_detail["bits"] == 32

    def test_unrecognised_format_falls_back_to_bare_type(self) -> None:
        result = from_openapi("string", "some-unknown-format")
        assert result.data_type == DataType.string

    def test_unrecognised_type_is_unknown_never_string(self) -> None:
        result = from_openapi("not-a-real-json-type", None)
        assert result.data_type == DataType.unknown


class TestFromXsdQname:
    def test_xs_decimal_is_decimal(self) -> None:
        assert from_xsd_qname("xs:decimal").data_type == DataType.decimal

    def test_xs_string_and_xs_token_both_map_to_string(self) -> None:
        assert from_xsd_qname("xs:string").data_type == DataType.string
        assert from_xsd_qname("xs:token").data_type == DataType.string

    def test_xs_anyType_is_unknown(self) -> None:
        assert from_xsd_qname("xs:anyType").data_type == DataType.unknown

    def test_unrecognised_qname_is_unknown_never_string(self) -> None:
        assert from_xsd_qname("xs:notARealType").data_type == DataType.unknown

    def test_int_and_long_record_distinct_bit_widths(self) -> None:
        assert from_xsd_qname("xs:int").type_detail["bits"] == 32
        assert from_xsd_qname("xs:long").type_detail["bits"] == 64

    def test_time_and_duration_use_existing_enum_members(self) -> None:
        assert from_xsd_qname("xs:time").data_type == DataType.time
        assert from_xsd_qname("xs:duration").data_type == DataType.duration


class TestFromAvro:
    def test_plain_string(self) -> None:
        assert from_avro("string", None).data_type == DataType.string

    def test_decimal_logical_type(self) -> None:
        result = from_avro("bytes", "decimal")
        assert result.data_type == DataType.decimal

    def test_date_logical_type(self) -> None:
        result = from_avro("int", "date")
        assert result.data_type == DataType.date

    def test_union_type_is_unknown_no_dominant_branch(self) -> None:
        result = from_avro(["null", "string"], None)
        assert result.data_type == DataType.unknown

    def test_unrecognised_type_is_unknown_never_string(self) -> None:
        assert from_avro("not-a-real-avro-type", None).data_type == DataType.unknown

    def test_logical_type_not_in_table_falls_back_to_base_type(self) -> None:
        result = from_avro("string", "some-custom-logical-type")
        assert result.data_type == DataType.string

    def test_non_string_non_list_type_is_unknown(self) -> None:
        # Defensive: Avro's own JSON grammar shouldn't produce this, but
        # from_avro's type signature is `object` precisely because
        # malformed input is possible - never silently defaults to string.
        assert from_avro(None, None).data_type == DataType.unknown
