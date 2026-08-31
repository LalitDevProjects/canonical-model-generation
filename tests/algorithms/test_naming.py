from __future__ import annotations

from algorithms.naming import (
    ALLOWED_ABBREVIATIONS,
    NamingContext,
    check_name,
    looks_denotes_identifier,
    looks_denotes_money,
)

_ABBREVIATIONS = {"dt": "date", "amt": "amount", "ref": "reference"}


def _ctx(**overrides: object) -> NamingContext:
    base: dict[str, object] = {
        "is_core": True,
        "data_type": "string",
        "type_name": "string",
        "offset_required": False,
        "denotes_money": False,
        "denotes_identifier": False,
    }
    base.update(overrides)
    return NamingContext(**base)  # type: ignore[arg-type]


class TestCheckName:
    def test_clean_name_has_no_violations(self) -> None:
        violations = check_name("Claim", "lossDate", _ctx(), abbreviations=_ABBREVIATIONS)
        assert violations == []

    def test_attribute_not_lower_camel_case(self) -> None:
        violations = check_name("Claim", "LossDate", _ctx(), abbreviations=_ABBREVIATIONS)
        assert any(v.kind == "case" for v in violations)

    def test_attribute_with_underscore_fails_case(self) -> None:
        violations = check_name("Claim", "loss_date", _ctx(), abbreviations=_ABBREVIATIONS)
        assert any(v.kind == "case" for v in violations)

    def test_entity_not_pascal_case(self) -> None:
        violations = check_name("claim", "lossDate", _ctx(), abbreviations=_ABBREVIATIONS)
        assert any(v.kind == "case" for v in violations)

    def test_unexpanded_abbreviation_flagged(self) -> None:
        violations = check_name("Claim", "lossAmt", _ctx(), abbreviations=_ABBREVIATIONS)
        assert any(v.kind == "abbreviation" for v in violations)

    def test_allowed_abbreviation_not_flagged(self) -> None:
        assert "ref" in ALLOWED_ABBREVIATIONS
        violations = check_name("Claim", "policyRef", _ctx(), abbreviations=_ABBREVIATIONS)
        assert not any(v.kind == "abbreviation" for v in violations)

    def test_region_marker_in_core_name_flagged(self) -> None:
        violations = check_name("Claim", "usLossDate", _ctx(is_core=True), abbreviations=_ABBREVIATIONS)
        assert any(v.kind == "region-marker" for v in violations)

    def test_region_marker_in_extension_name_not_flagged(self) -> None:
        violations = check_name("Claim", "usLossDate", _ctx(is_core=False), abbreviations=_ABBREVIATIONS)
        assert not any(v.kind == "region-marker" for v in violations)

    def test_boolean_not_positively_phrased(self) -> None:
        violations = check_name(
            "Claim", "active", _ctx(data_type="boolean"), abbreviations=_ABBREVIATIONS
        )
        assert any(v.kind == "boolean" for v in violations)

    def test_boolean_positively_phrased_is_fine(self) -> None:
        violations = check_name(
            "Claim", "isActive", _ctx(data_type="boolean"), abbreviations=_ABBREVIATIONS
        )
        assert not any(v.kind == "boolean" for v in violations)

    def test_boolean_has_prefix_is_fine(self) -> None:
        violations = check_name(
            "Claim", "hasCoverage", _ctx(data_type="boolean"), abbreviations=_ABBREVIATIONS
        )
        assert not any(v.kind == "boolean" for v in violations)

    def test_money_without_monetary_amount_type_flagged(self) -> None:
        violations = check_name(
            "Claim", "reserveAmount", _ctx(denotes_money=True, type_name="decimal"), abbreviations=_ABBREVIATIONS
        )
        assert any(v.kind == "money" for v in violations)

    def test_money_with_monetary_amount_type_is_fine(self) -> None:
        violations = check_name(
            "Claim", "reserveAmount", _ctx(denotes_money=True, type_name="MonetaryAmount"), abbreviations=_ABBREVIATIONS
        )
        assert not any(v.kind == "money" for v in violations)

    def test_identifier_without_identifier_type_flagged(self) -> None:
        violations = check_name(
            "Claim", "claimId", _ctx(denotes_identifier=True, type_name="string"), abbreviations=_ABBREVIATIONS
        )
        assert any(v.kind == "identifier" for v in violations)

    def test_identifier_with_identifier_type_is_fine(self) -> None:
        violations = check_name(
            "Claim", "claimId", _ctx(denotes_identifier=True, type_name="Identifier"), abbreviations=_ABBREVIATIONS
        )
        assert not any(v.kind == "identifier" for v in violations)

    def test_datetime_without_offset_flagged(self) -> None:
        violations = check_name(
            "Claim", "recordedAt", _ctx(data_type="dateTime", offset_required=False), abbreviations=_ABBREVIATIONS
        )
        assert any(v.kind == "datetime" for v in violations)

    def test_datetime_with_offset_is_fine(self) -> None:
        violations = check_name(
            "Claim", "recordedAt", _ctx(data_type="dateTime", offset_required=True), abbreviations=_ABBREVIATIONS
        )
        assert not any(v.kind == "datetime" for v in violations)

    def test_multiple_violations_all_reported(self) -> None:
        violations = check_name("claim", "loss_amt", _ctx(), abbreviations=_ABBREVIATIONS)
        kinds = {v.kind for v in violations}
        assert "case" in kinds  # both entity and attribute case fail
        assert "abbreviation" in kinds


class TestLooksDenotesHeuristics:
    def test_looks_denotes_money(self) -> None:
        assert looks_denotes_money(("reserve", "amount")) is True
        assert looks_denotes_money(("claim", "date")) is False

    def test_looks_denotes_identifier(self) -> None:
        assert looks_denotes_identifier(("claim", "id")) is True
        assert looks_denotes_identifier(("claim", "date")) is False
