"""Hermetic tests for mapping/roundtrip.py::generate_round_trip_tests -
a declared-loss case that still passes (Appendix C's own LossDate
scenario), and a genuinely undeclared-loss case that raises
RoundTripFailure (the S8 gate)."""

from __future__ import annotations

import pytest
from mapping_builders import attribute_record, mapping_spec, transform_entry

from mapping.compiler import compile_spec
from mapping.roundtrip import RoundTripFailure, generate_round_trip_tests, summarise, synthesise_instance

pytestmark = pytest.mark.unit


class TestSynthesiseInstance:
    def test_enumeration_cycles_deterministically_by_seed(self) -> None:
        rec = attribute_record(path="status", enumeration=[{"value": "NEW"}, {"value": "OLD"}])
        assert synthesise_instance([rec], seed=0)["status"] == "NEW"
        assert synthesise_instance([rec], seed=1)["status"] == "OLD"
        assert synthesise_instance([rec], seed=2)["status"] == "NEW"

    def test_date_type_produces_iso_string(self) -> None:
        rec = attribute_record(path="d", data_type="date")
        value = synthesise_instance([rec], seed=0)["d"]
        assert value == "2020-01-01"

    def test_date_time_type_produces_iso_string(self) -> None:
        rec = attribute_record(path="dt", data_type="dateTime")
        value = synthesise_instance([rec], seed=1)["dt"]
        assert value == "2020-01-02T01:00:00"

    def test_integer_type_produces_deterministic_integer(self) -> None:
        rec = attribute_record(path="n", data_type="integer")
        assert synthesise_instance([rec], seed=2)["n"] == 3

    def test_decimal_type_produces_deterministic_float(self) -> None:
        rec = attribute_record(path="n", data_type="decimal")
        assert synthesise_instance([rec], seed=1)["n"] == 2.5

    def test_boolean_type_alternates_by_seed(self) -> None:
        rec = attribute_record(path="b", data_type="boolean")
        assert synthesise_instance([rec], seed=0)["b"] is True
        assert synthesise_instance([rec], seed=1)["b"] is False

    def test_same_seed_is_deterministic(self) -> None:
        rec = attribute_record(path="x", data_type="string")
        assert synthesise_instance([rec], seed=3) == synthesise_instance([rec], seed=3)


class TestDeclaredLossStillPasses:
    def test_precision_loss_with_a_note_yields_pass(self) -> None:
        region_ir = [attribute_record(path="ClaimHeader.LossDate", data_type="date")]
        spec = mapping_spec(
            direction="bidirectional",
            mappings=[
                transform_entry(
                    canonical="incident.occurrenceDateTime",
                    region="ClaimHeader.LossDate",
                    transform="parseDate(fmt='yyyy-MM-dd') -> instantAtStartOfDay(zone='Europe/London')",
                    weight=5,
                    on_failure="reject",
                    note="DECLARED LOSS. Time component discarded on reverse mapping.",
                )
            ],
        )
        plan = compile_spec(spec, region_ir, canonical_types={"incident.occurrenceDateTime": "dateTime"})
        cases = generate_round_trip_tests(plan, region_ir, n=24)
        assert all(case.passed for case in cases)
        summary = summarise(cases, plan)
        assert summary["result"] == "pass"
        assert summary["declaredLosses"] == [
            {
                "path": "ClaimHeader.LossDate",
                "kind": "precision",
                "detail": "DECLARED LOSS. Time component discarded on reverse mapping.",
            }
        ]


class TestUndeclaredLossFails:
    def test_lossy_transform_without_a_note_fails_when_critical(self) -> None:
        # normaliseCase is declared lossy (Section 10.3) but this entry
        # carries no note - an undeclared loss on a weight>=5 attribute.
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            direction="bidirectional",
            mappings=[
                transform_entry(
                    canonical="c",
                    region="x",
                    transform="normaliseCase(mode='upper')",
                    weight=5,
                    on_failure="reject",
                )
            ],
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        with pytest.raises(RoundTripFailure):
            generate_round_trip_tests(plan, region_ir, n=4)

    def test_undefined_reverse_is_a_declared_structural_loss_not_a_failure(self) -> None:
        # coalesce has no reverse at all, but that's a *structural*,
        # always-declared loss (mapping/interpreter.py's own
        # declared_loss_kind="undefined-reverse"), not an undeclared one -
        # generation must not raise for this on its own.
        region_ir = [attribute_record(path="x", data_type="array")]
        spec = mapping_spec(
            direction="toCanonical",
            mappings=[transform_entry(canonical="c", region="x", transform="coalesce", weight=1)],
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        cases = generate_round_trip_tests(plan, region_ir, n=4)
        assert not any(case.undeclared_losses for case in cases)
        summary = summarise(cases, plan)
        assert summary["declaredLosses"] == [
            {
                "path": "x",
                "kind": "undefined-reverse",
                "detail": "the transform chain for this entry has no reverse; the field does not round-trip",
            }
        ]


class TestDiffAttributesSkipsRegionlessSteps:
    def test_constant_entry_with_no_region_path_is_excluded_from_the_diff(self) -> None:
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            direction="toCanonical",
            mappings=[
                transform_entry(canonical="c", region="x", transform="identity", weight=1),
                {
                    "canonical": "currency",
                    "transform": "constant(\"GBP\")",
                    "weight": 1,
                    "evidence": ["evref://uk/git/fixture-artefact@" + "a" * 16 + "#/currency"],
                },
            ],
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        assert plan.steps[1].region_path is None
        cases = generate_round_trip_tests(plan, region_ir, n=3)
        assert not any(case.declared_losses or case.undeclared_losses for case in cases)


class TestSummariseShape:
    def test_generated_count_and_assertion_text(self) -> None:
        region_ir = [attribute_record(path="x", data_type="string")]
        spec = mapping_spec(
            mappings=[transform_entry(canonical="c", region="x", transform="identity", weight=1)]
        )
        plan = compile_spec(spec, region_ir, canonical_types={})
        cases = generate_round_trip_tests(plan, region_ir, n=6)
        summary = summarise(cases, plan)
        assert summary["generated"] == 6
        assert summary["assertion"] == "no attribute with weight >= 5 is lost region -> canonical -> region"
        assert summary["declaredLosses"] == []
        assert summary["result"] == "pass"
