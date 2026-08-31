"""Hermetic tests for mapping/compiler.py::compile_spec - T1-T4, plus the
builder-added D1 reversibility check. One synthetic failing fixture per
check, and a happy-path compile proving a passing spec produces a real
Plan."""

from __future__ import annotations

import pytest
from mapping_builders import attribute_record, disposition_entry, mapping_spec, transform_entry

from mapping.compiler import CompilationFailed, compile_spec, infer_output_type, type_compatible
from mapping.interpreter import Plan
from mapping.parser import parse_transform_expr

pytestmark = pytest.mark.unit


def _checks(exc_info: pytest.ExceptionInfo[CompilationFailed]) -> set[str]:
    return {e.check for e in exc_info.value.errors}


class TestT1Totality:
    def test_uncovered_region_attribute_fails(self) -> None:
        region_ir = [attribute_record(path="ClaimHeader.ClaimNo")]
        # C10's own mappings[] carries min_length=1, so a spec covering
        # some unrelated path (not ClaimHeader.ClaimNo) is the minimal way
        # to leave a real region attribute genuinely uncovered.
        spec = mapping_spec(mappings=[disposition_entry(region="SomethingElse")])
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T1" in _checks(exc_info)

    def test_fully_covered_region_passes_t1(self) -> None:
        region_ir = [attribute_record(path="ClaimHeader.ClaimNo")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="claimReference", region="ClaimHeader.ClaimNo", transform="identity")]
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        assert isinstance(plan, Plan)


class TestT2WeightRule:
    def test_weight_5_with_skip_fails(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity", weight=5, on_failure="skip")]
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T2" in _checks(exc_info)

    def test_weight_5_with_default_fails(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity", weight=5, on_failure="default")]
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T2" in _checks(exc_info)

    def test_weight_5_with_reject_passes(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity", weight=5, on_failure="reject")]
        )
        compile_spec(spec, region_ir, canonical_types={})


class TestT3TypeFit:
    def test_incompatible_type_fails(self) -> None:
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity")]
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={"c": "integer"})
        assert "T3" in _checks(exc_info)

    def test_compatible_type_passes(self) -> None:
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity")]
        )
        compile_spec(spec, region_ir, canonical_types={"c": "string"})

    def test_unknown_canonical_path_skips_t3(self) -> None:
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity")]
        )
        # canonical_types has no entry for "c" at all - T3 can't verify, must not fail.
        compile_spec(spec, region_ir, canonical_types={})


class TestT4ValueMapCompleteness:
    def test_missing_value_with_no_unmapped_policy_fails(self) -> None:
        region_ir = [
            attribute_record(
                path="x",
                enumeration=[{"value": "NEW"}, {"value": "CLS"}],
            )
        ]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="valueMap(map='m')")],
            value_maps={"m": {"mappings": {"NEW": "NOTIFIED"}}},
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T4" in _checks(exc_info)

    def test_missing_value_with_escalate_policy_passes(self) -> None:
        region_ir = [
            attribute_record(path="x", enumeration=[{"value": "NEW"}, {"value": "CLS"}])
        ]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="valueMap(map='m')")],
            value_maps={"m": {"mappings": {"NEW": "NOTIFIED"}, "unmappedValues": "escalate"}},
        )
        compile_spec(spec, region_ir, canonical_types={})

    def test_unknown_map_id_fails(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="valueMap(map='nope')")]
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T4" in _checks(exc_info)

    def test_non_injective_map_fails_when_bidirectional(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            direction="bidirectional",
            mappings=[
                transform_entry(canonical="c", region="x", transform="valueMap(map='m')", weight=1)
            ],
            value_maps={"m": {"mappings": {"NEW": "SAME", "OLD": "SAME"}}},
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "T4" in _checks(exc_info)

    def test_non_injective_map_passes_when_to_canonical_only(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            direction="toCanonical",
            mappings=[
                transform_entry(canonical="c", region="x", transform="valueMap(map='m')", weight=1)
            ],
            value_maps={"m": {"mappings": {"NEW": "SAME", "OLD": "SAME"}}},
        )
        compile_spec(spec, region_ir, canonical_types={})


class TestD1Reversibility:
    def test_coalesce_in_bidirectional_spec_fails(self) -> None:
        region_ir = [attribute_record(path="x", data_type="array")]
        spec = mapping_spec(
            direction="bidirectional",
            mappings=[transform_entry(canonical="c", region="x", transform="coalesce", weight=1)],
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "D1" in _checks(exc_info)

    def test_coalesce_in_to_canonical_spec_passes(self) -> None:
        region_ir = [attribute_record(path="x", data_type="array")]
        spec = mapping_spec(
            direction="toCanonical",
            mappings=[transform_entry(canonical="c", region="x", transform="coalesce", weight=1)],
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        assert plan.steps[0].reversible is False

    def test_constant_top_level_in_bidirectional_spec_fails(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            direction="bidirectional",
            mappings=[transform_entry(canonical="c", region="x", transform='constant("GBP")', weight=1)],
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "D1" in _checks(exc_info)


class TestMalformedTransformExpression:
    def test_unparseable_transform_string_is_a_compile_error(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="not a valid call (")]
        )
        with pytest.raises(CompilationFailed) as exc_info:
            compile_spec(spec, region_ir, canonical_types={})
        assert "PARSE" in _checks(exc_info)


class TestBuildPlan:
    def test_disposition_entries_are_compiled_as_non_reversible_steps(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(mappings=[disposition_entry(region="x")])
        plan = compile_spec(spec, region_ir, canonical_types={})
        assert plan.steps[0].disposition_status == "unmapped"
        assert plan.steps[0].reversible is False

    def test_value_map_args_are_resolved_at_compile_time(self) -> None:
        region_ir = [attribute_record(path="x")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="valueMap(map='m')")],
            value_maps={"m": {"mappings": {"NEW": "NOTIFIED"}, "unmappedValues": "passthrough"}},
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        call = plan.steps[0].transform_chain[0]
        assert call.args["resolved_map"] == {"NEW": "NOTIFIED"}
        assert call.args["unmapped_values"] == "passthrough"


class TestInferOutputTypeAndCompatibility:
    def test_parse_date_without_zone_infers_date(self) -> None:
        chain = parse_transform_expr("parseDate(fmt='yyyy-MM-dd')")
        assert infer_output_type(chain, "string") == "date"

    def test_parse_date_with_zone_infers_date_time(self) -> None:
        chain = parse_transform_expr("parseDate(fmt='yyyy-MM-dd', zone='Europe/London')")
        assert infer_output_type(chain, "string") == "dateTime"

    def test_identity_preserves_source_type(self) -> None:
        chain = parse_transform_expr("identity")
        assert infer_output_type(chain, "boolean") == "boolean"

    def test_constant_produces_unknown_type_always_compatible(self) -> None:
        chain = parse_transform_expr('constant("GBP")')
        assert infer_output_type(chain, None) is None
        assert type_compatible(None, "string") is True

    def test_widening_pairs_are_compatible(self) -> None:
        assert type_compatible("date", "dateTime") is True
        assert type_compatible("integer", "decimal") is True
        assert type_compatible("MonetaryAmount", "object") is True

    def test_mismatched_types_are_incompatible(self) -> None:
        assert type_compatible("string", "integer") is False
