from __future__ import annotations

import pytest

from agents.validation import (
    Guardrail,
    Violation,
    evaluate,
    validate_cross_artefact,
    validate_provenance,
    validate_reference,
    validate_schema,
)
from agents.validation import SchemaValidationFailed


class TestValidateSchema:
    def test_valid_output_is_returned_unchanged(self) -> None:
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}
        output = {"x": "hello"}
        assert validate_schema(output, schema) == output

    def test_invalid_output_raises_schema_validation_failed(self) -> None:
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}
        with pytest.raises(SchemaValidationFailed):
            validate_schema({"x": 42}, schema)

    def test_missing_required_field_raises(self) -> None:
        schema = {"type": "object", "required": ["x"]}
        with pytest.raises(SchemaValidationFailed):
            validate_schema({}, schema)


class TestValidateReference:
    def test_resolvable_reference_produces_no_violations(self) -> None:
        refs = ["evref://us/git/art-1@1234567890abcdef#/x"]
        assert validate_reference(refs, {"art-1"}) == []

    def test_unresolvable_reference_produces_a_v2_violation(self) -> None:
        refs = ["evref://us/git/art-missing@1234567890abcdef#/x"]
        violations = validate_reference(refs, {"art-1"})
        assert len(violations) == 1
        assert violations[0].level == "V2"
        assert violations[0].code == "unresolvable-reference"

    def test_malformed_evref_produces_a_violation(self) -> None:
        violations = validate_reference(["not-an-evref"], {"art-1"})
        assert len(violations) == 1
        assert violations[0].level == "V2"

    def test_empty_ref_list_produces_no_violations(self) -> None:
        assert validate_reference([], {"art-1"}) == []


class TestValidateProvenance:
    def test_always_returns_empty_at_increment_6(self) -> None:
        assert validate_provenance({"anything": "goes"}) == []
        assert validate_provenance({}) == []


class TestEvaluate:
    def test_no_guardrails_means_no_violations(self) -> None:
        assert evaluate([], {}, ctx=None) == []  # type: ignore[arg-type]

    def test_a_passing_guardrail_contributes_nothing(self) -> None:
        guardrail = Guardrail(id="G1", description="always passes", check=lambda output, ctx: [])
        assert evaluate([guardrail], {}, ctx=None) == []  # type: ignore[arg-type]

    def test_a_failing_guardrail_contributes_its_violations(self) -> None:
        violation = Violation(level="V4", code="G1", detail="failed")
        guardrail = Guardrail(id="G1", description="always fails", check=lambda output, ctx: [violation])
        assert evaluate([guardrail], {}, ctx=None) == [violation]  # type: ignore[arg-type]

    def test_every_guardrail_runs_the_ladder_does_not_short_circuit(self) -> None:
        v1 = Violation(level="V4", code="G1", detail="one")
        v2 = Violation(level="V4", code="G2", detail="two")
        g1 = Guardrail(id="G1", description="", check=lambda output, ctx: [v1])
        g2 = Guardrail(id="G2", description="", check=lambda output, ctx: [v2])
        assert evaluate([g1, g2], {}, ctx=None) == [v1, v2]  # type: ignore[arg-type]


class TestValidateCrossArtefact:
    def test_dispatches_to_the_real_i2_check(self) -> None:
        from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
        from generated.C5.AttributeRecord._1_0 import C5Attributerecord

        cluster = C6Conceptcluster.model_validate({
            "clusterId": "cluster://x",
            "proposedConcept": "claimDate",
            "members": [{"attributeId": "attr://us/claims-v1/x", "region": "us", "role": "core", "pairScore": 1.0}],
            "confidence": 0.9,
            "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
        })
        violations = validate_cross_artefact("I2", [cluster], [], "11111111-1111-1111-1111-111111111111")
        assert len(violations) == 1
        assert violations[0].invariant == "I2"

    def test_unknown_kind_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            validate_cross_artefact("I9")  # type: ignore[arg-type]
