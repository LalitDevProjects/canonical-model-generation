"""Hermetic tests for the 14-entry closed transform library (Section
10.3). Every transform's forward + reverse is exercised, including the
documented lossy and reverse-undefined cases."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mapping.transforms import TRANSFORMS, TransformError

pytestmark = pytest.mark.unit


def test_all_14_transforms_registered() -> None:
    expected = {
        "identity", "parseDate", "formatDate", "instantAtStartOfDay", "valueMap",
        "toMonetaryAmount", "toIdentifier", "decompose", "compose", "concat",
        "coalesce", "constant", "scale", "normaliseCase",
    }
    assert set(TRANSFORMS) == expected


class TestIdentity:
    def test_forward_returns_value_unchanged(self) -> None:
        assert TRANSFORMS["identity"].forward("x") == "x"

    def test_reverse_is_identity(self) -> None:
        assert TRANSFORMS["identity"].reverse is TRANSFORMS["identity"].forward

    def test_not_lossy(self) -> None:
        assert TRANSFORMS["identity"].lossy is False


class TestParseDateFormatDate:
    def test_parse_date_without_zone_returns_date(self) -> None:
        result = TRANSFORMS["parseDate"].forward("2026-08-31", fmt="yyyy-MM-dd")
        assert result == date(2026, 8, 31)

    def test_parse_date_with_zone_returns_datetime(self) -> None:
        result = TRANSFORMS["parseDate"].forward("2026-08-31", fmt="yyyy-MM-dd", zone="Europe/London")
        assert result == datetime(2026, 8, 31, tzinfo=ZoneInfo("Europe/London"))

    def test_parse_date_rejects_non_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["parseDate"].forward(123, fmt="yyyy-MM-dd")

    def test_parse_date_rejects_malformed_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["parseDate"].forward("not-a-date", fmt="yyyy-MM-dd")

    def test_format_date_forward(self) -> None:
        assert TRANSFORMS["formatDate"].forward(date(2026, 8, 31), fmt="yyyy-MM-dd") == "2026-08-31"

    def test_format_date_rejects_non_date(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["formatDate"].forward("2026-08-31", fmt="yyyy-MM-dd")

    def test_parse_date_reverse_is_format_date(self) -> None:
        assert TRANSFORMS["parseDate"].reverse is not None
        assert TRANSFORMS["parseDate"].reverse(date(2026, 8, 31), fmt="yyyy-MM-dd") == "2026-08-31"

    def test_format_date_reverse_is_parse_date(self) -> None:
        assert TRANSFORMS["formatDate"].reverse is not None
        assert TRANSFORMS["formatDate"].reverse("2026-08-31", fmt="yyyy-MM-dd") == date(2026, 8, 31)

    def test_parse_date_lossy(self) -> None:
        assert TRANSFORMS["parseDate"].lossy is True


class TestInstantAtStartOfDay:
    def test_forward(self) -> None:
        result = TRANSFORMS["instantAtStartOfDay"].forward(date(2026, 8, 31), zone="Europe/London")
        assert result == datetime(2026, 8, 31, 0, 0, tzinfo=ZoneInfo("Europe/London"))

    def test_forward_rejects_datetime(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["instantAtStartOfDay"].forward(
                datetime(2026, 8, 31, 10), zone="Europe/London"
            )

    def test_reverse_recovers_the_date(self) -> None:
        instant = datetime(2026, 8, 31, 0, 0, tzinfo=ZoneInfo("Europe/London"))
        assert TRANSFORMS["instantAtStartOfDay"].reverse is not None
        assert TRANSFORMS["instantAtStartOfDay"].reverse(instant, zone="Europe/London") == date(2026, 8, 31)

    def test_reverse_discards_non_midnight_time_declared_lossy(self) -> None:
        instant = datetime(2026, 8, 31, 14, 30, tzinfo=ZoneInfo("Europe/London"))
        assert TRANSFORMS["instantAtStartOfDay"].reverse is not None
        assert TRANSFORMS["instantAtStartOfDay"].reverse(instant, zone="Europe/London") == date(2026, 8, 31)
        assert TRANSFORMS["instantAtStartOfDay"].lossy is True

    def test_reverse_rejects_naive_non_datetime(self) -> None:
        assert TRANSFORMS["instantAtStartOfDay"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["instantAtStartOfDay"].reverse("not-a-datetime", zone="Europe/London")


class TestValueMap:
    MAP = {"NEW": "NOTIFIED", "CLS": "CLOSED"}

    def test_forward_maps_known_value(self) -> None:
        result = TRANSFORMS["valueMap"].forward("NEW", map="ClaimStatus.uk", resolved_map=self.MAP)
        assert result == "NOTIFIED"

    def test_forward_raises_on_unmapped_by_default(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["valueMap"].forward("XXX", map="ClaimStatus.uk", resolved_map=self.MAP)

    def test_forward_passthrough_on_unmapped(self) -> None:
        result = TRANSFORMS["valueMap"].forward(
            "XXX", map="ClaimStatus.uk", resolved_map=self.MAP, unmapped_values="passthrough"
        )
        assert result == "XXX"

    def test_reverse_maps_known_value(self) -> None:
        assert TRANSFORMS["valueMap"].reverse is not None
        result = TRANSFORMS["valueMap"].reverse("NOTIFIED", map="ClaimStatus.uk", resolved_map=self.MAP)
        assert result == "NEW"

    def test_reverse_raises_on_unmapped(self) -> None:
        assert TRANSFORMS["valueMap"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["valueMap"].reverse("UNKNOWN", map="ClaimStatus.uk", resolved_map=self.MAP)

    def test_reverse_passthrough_on_unmapped(self) -> None:
        assert TRANSFORMS["valueMap"].reverse is not None
        result = TRANSFORMS["valueMap"].reverse(
            "UNKNOWN", map="ClaimStatus.uk", resolved_map=self.MAP, unmapped_values="passthrough"
        )
        assert result == "UNKNOWN"


class TestToMonetaryAmount:
    def test_forward_from_number(self) -> None:
        result = TRANSFORMS["toMonetaryAmount"].forward(100.5, currency="GBP")
        assert result == {"amount": 100.5, "currency": "GBP"}

    def test_forward_from_string(self) -> None:
        result = TRANSFORMS["toMonetaryAmount"].forward("100.5", currency="GBP")
        assert result == {"amount": 100.5, "currency": "GBP"}

    def test_forward_rejects_non_numeric_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["toMonetaryAmount"].forward("not-a-number", currency="GBP")

    def test_forward_rejects_non_number_non_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["toMonetaryAmount"].forward([100], currency="GBP")

    def test_reverse_extracts_amount(self) -> None:
        assert TRANSFORMS["toMonetaryAmount"].reverse is not None
        result = TRANSFORMS["toMonetaryAmount"].reverse({"amount": 100.5, "currency": "GBP"}, currency="GBP")
        assert result == 100.5

    def test_reverse_rejects_non_object(self) -> None:
        assert TRANSFORMS["toMonetaryAmount"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["toMonetaryAmount"].reverse("100.5", currency="GBP")


class TestToIdentifier:
    def test_forward(self) -> None:
        result = TRANSFORMS["toIdentifier"].forward(
            "CLM-123", scheme="urn:client:uk:claim", issuer="uk-claims"
        )
        assert result == {"value": "CLM-123", "scheme": "urn:client:uk:claim", "issuer": "uk-claims"}

    def test_forward_rejects_non_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["toIdentifier"].forward(123, scheme="urn:client:uk:claim", issuer="uk-claims")

    def test_reverse(self) -> None:
        assert TRANSFORMS["toIdentifier"].reverse is not None
        identifier = {"value": "CLM-123", "scheme": "urn:client:uk:claim", "issuer": "uk-claims"}
        result = TRANSFORMS["toIdentifier"].reverse(
            identifier, scheme="urn:client:uk:claim", issuer="uk-claims"
        )
        assert result == "CLM-123"

    def test_reverse_rejects_non_identifier_object(self) -> None:
        assert TRANSFORMS["toIdentifier"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["toIdentifier"].reverse(
                "not-an-identifier", scheme="urn:client:uk:claim", issuer="uk-claims"
            )


class TestDecomposeCompose:
    PATTERN = r"(?P<first>\w+) (?P<last>\w+)"
    TEMPLATE = "{first} {last}"

    def test_decompose_forward(self) -> None:
        result = TRANSFORMS["decompose"].forward("Jane Smith", pattern=self.PATTERN)
        assert result == {"first": "Jane", "last": "Smith"}

    def test_decompose_rejects_non_matching_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["decompose"].forward("JaneSmith", pattern=self.PATTERN)

    def test_decompose_rejects_non_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["decompose"].forward(123, pattern=self.PATTERN)

    def test_compose_forward(self) -> None:
        result = TRANSFORMS["compose"].forward({"first": "Jane", "last": "Smith"}, template=self.TEMPLATE)
        assert result == "Jane Smith"

    def test_compose_rejects_non_object(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["compose"].forward("not-an-object", template=self.TEMPLATE)

    def test_compose_rejects_missing_field(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["compose"].forward({"first": "Jane"}, template=self.TEMPLATE)

    def test_decompose_reverse_uses_template(self) -> None:
        assert TRANSFORMS["decompose"].reverse is not None
        result = TRANSFORMS["decompose"].reverse(
            {"first": "Jane", "last": "Smith"}, pattern=self.PATTERN, template=self.TEMPLATE
        )
        assert result == "Jane Smith"

    def test_decompose_reverse_requires_template(self) -> None:
        assert TRANSFORMS["decompose"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["decompose"].reverse({"first": "Jane", "last": "Smith"}, pattern=self.PATTERN)

    def test_compose_reverse_uses_pattern(self) -> None:
        assert TRANSFORMS["compose"].reverse is not None
        result = TRANSFORMS["compose"].reverse("Jane Smith", template=self.TEMPLATE, pattern=self.PATTERN)
        assert result == {"first": "Jane", "last": "Smith"}

    def test_compose_reverse_requires_pattern(self) -> None:
        assert TRANSFORMS["compose"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["compose"].reverse("Jane Smith", template=self.TEMPLATE)


class TestConcat:
    def test_forward(self) -> None:
        assert TRANSFORMS["concat"].forward(["a", "b", "c"], separator="-") == "a-b-c"

    def test_forward_rejects_non_list(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["concat"].forward("abc", separator="-")

    def test_reverse_splits(self) -> None:
        assert TRANSFORMS["concat"].reverse is not None
        assert TRANSFORMS["concat"].reverse("a-b-c", separator="-") == ["a", "b", "c"]

    def test_reverse_rejects_non_string(self) -> None:
        assert TRANSFORMS["concat"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["concat"].reverse(["a", "b"], separator="-")


class TestCoalesce:
    def test_forward_returns_first_non_null(self) -> None:
        assert TRANSFORMS["coalesce"].forward([None, None, "x", "y"]) == "x"

    def test_forward_raises_when_all_null(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["coalesce"].forward([None, None])

    def test_forward_rejects_non_list(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["coalesce"].forward("x")

    def test_reverse_is_undefined(self) -> None:
        assert TRANSFORMS["coalesce"].reverse is None


class TestConstant:
    def test_forward_ignores_input_value(self) -> None:
        assert TRANSFORMS["constant"].forward("anything", const="GBP") == "GBP"
        assert TRANSFORMS["constant"].forward(None, const="GBP") == "GBP"

    def test_reverse_is_undefined(self) -> None:
        assert TRANSFORMS["constant"].reverse is None


class TestScale:
    def test_forward(self) -> None:
        assert TRANSFORMS["scale"].forward(100, factor=0.01) == 1.0

    def test_forward_rejects_non_number(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["scale"].forward("100", factor=0.01)

    def test_reverse_inverts_factor(self) -> None:
        assert TRANSFORMS["scale"].reverse is not None
        assert TRANSFORMS["scale"].reverse(1.0, factor=0.01) == 100.0

    def test_reverse_rejects_zero_factor(self) -> None:
        assert TRANSFORMS["scale"].reverse is not None
        with pytest.raises(TransformError):
            TRANSFORMS["scale"].reverse(1.0, factor=0)


class TestNormaliseCase:
    def test_forward_upper(self) -> None:
        assert TRANSFORMS["normaliseCase"].forward("abc", mode="upper") == "ABC"

    def test_forward_lower(self) -> None:
        assert TRANSFORMS["normaliseCase"].forward("ABC", mode="lower") == "abc"

    def test_forward_title(self) -> None:
        assert TRANSFORMS["normaliseCase"].forward("jane smith", mode="title") == "Jane Smith"

    def test_forward_rejects_unknown_mode(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["normaliseCase"].forward("abc", mode="shout")

    def test_forward_rejects_non_string(self) -> None:
        with pytest.raises(TransformError):
            TRANSFORMS["normaliseCase"].forward(123, mode="upper")

    def test_reverse_is_identity_and_declared_lossy(self) -> None:
        assert TRANSFORMS["normaliseCase"].reverse is TRANSFORMS["identity"].forward
        assert TRANSFORMS["normaliseCase"].lossy is True
