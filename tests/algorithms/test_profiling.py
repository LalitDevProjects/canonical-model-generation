from __future__ import annotations

from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from algorithms.profiling import (
    Finding,
    TYPE_FAMILY,
    canonical_tokens,
    documented_values,
    head_noun,
    looks_monetary,
    looks_temporal,
    profile,
)
from generated.common.defs import DataType

RUN_ID = uuid4()


def _attr(local_name: str, data_type: str, **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://us/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": "us",
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


class TestCanonicalTokens:
    def test_camel_case_split(self) -> None:
        assert canonical_tokens("lossDate") == ("loss", "date")

    def test_snake_case_split(self) -> None:
        assert canonical_tokens("loss_date") == ("loss", "date")

    def test_single_token(self) -> None:
        assert canonical_tokens("status") == ("status",)

    def test_empty_string(self) -> None:
        assert canonical_tokens("") == ()


class TestHeadNoun:
    def test_last_token_is_head_noun(self) -> None:
        assert head_noun(("loss", "date")) == "date"

    def test_empty_tokens_gives_empty_string(self) -> None:
        assert head_noun(()) == ""


class TestLooksTemporal:
    def test_date_token_matches(self) -> None:
        assert looks_temporal(("loss", "date"), None) is True

    def test_no_temporal_signal(self) -> None:
        assert looks_temporal(("claimant",), None) is False

    def test_description_can_trigger_it(self) -> None:
        assert looks_temporal(("received",), "the timestamp of receipt") is True


class TestLooksMonetary:
    def test_amount_token_matches(self) -> None:
        assert looks_monetary(("reserve", "amount"), None) is True

    def test_no_monetary_signal(self) -> None:
        assert looks_monetary(("claimant",), None) is False


class TestDocumentedValues:
    def test_one_of_phrasing_matches(self) -> None:
        assert documented_values("one of OPEN, CLOSED or PENDING") is True

    def test_plain_description_does_not_match(self) -> None:
        assert documented_values("the claimant's full legal name") is False

    def test_none_description(self) -> None:
        assert documented_values(None) is False


class TestProfile:
    def test_declared_date_type_raises_no_type_suspicion(self) -> None:
        rec = _attr("lossDate", "date")
        profiled = profile(rec, siblings=[])
        assert profiled.findings == ()

    def test_string_that_looks_temporal_raises_type_suspicion(self) -> None:
        rec = _attr("lossDate", "string")
        profiled = profile(rec, siblings=[])
        assert Finding("type-suspicion", "string that denotes a date") in profiled.findings

    def test_string_that_looks_monetary_raises_type_suspicion(self) -> None:
        rec = _attr("reserveAmount", "string")
        profiled = profile(rec, siblings=[])
        assert Finding("type-suspicion", "string that denotes an amount") in profiled.findings

    def test_string_with_numeric_pattern_constraint_raises_type_suspicion(self) -> None:
        rec = _attr(
            "claimant", "string",
            constraints=[{"kind": "pattern", "expression": r"^\d{6}$"}],
        )
        profiled = profile(rec, siblings=[])
        assert Finding("type-suspicion", "string constrained to numerics") in profiled.findings

    def test_unknown_type_raises_opaque_type(self) -> None:
        rec = _attr("mystery", "unknown")
        profiled = profile(rec, siblings=[])
        assert Finding("opaque-type", "no type declared; requires confirmation") in profiled.findings

    def test_undeclared_enum_raises_finding(self) -> None:
        rec = _attr(
            "status", "string",
            semantics={"description": "one of OPEN, CLOSED"},
        )
        profiled = profile(rec, siblings=[])
        assert Finding("undeclared-enum", "values documented but not declared") in profiled.findings

    def test_declared_enum_does_not_raise_undeclared_enum(self) -> None:
        rec = _attr(
            "status", "string",
            semantics={"description": "one of OPEN, CLOSED"},
            enumeration=[{"value": "OPEN"}, {"value": "CLOSED"}],
        )
        profiled = profile(rec, siblings=[])
        assert not any(f.kind == "undeclared-enum" for f in profiled.findings)

    def test_missing_semantics_does_not_crash(self) -> None:
        rec = _attr("lossDate", "string")
        assert rec.semantics is None
        profiled = profile(rec, siblings=[])
        assert Finding("type-suspicion", "string that denotes a date") in profiled.findings

    def test_type_family_and_sibling_names_populated(self) -> None:
        rec = _attr("reserveAmount", "decimal")
        sibling = _attr("claimId", "string")
        profiled = profile(rec, siblings=[sibling])
        assert profiled.type_family == TYPE_FAMILY[DataType.decimal]
        assert profiled.sibling_names == ("claimId",)
        assert profiled.head_noun == "amount"
