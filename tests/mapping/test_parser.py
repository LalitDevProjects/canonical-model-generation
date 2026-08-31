"""Hermetic tests for mapping/parser.py's transform-expression parser
(Section 10.2's TransformExpr/TransformCall/ArgList grammar)."""

from __future__ import annotations

import pytest

from mapping.parser import MappingParseError, TransformCall, parse_transform_expr

pytestmark = pytest.mark.unit


def test_zero_arg_call() -> None:
    assert parse_transform_expr("identity") == [TransformCall(name="identity", args={})]


def test_single_call_with_kwargs() -> None:
    result = parse_transform_expr("toIdentifier(scheme=\"urn:client:uk:claim\", issuer=\"uk-claims\")")
    assert result == [
        TransformCall(name="toIdentifier", args={"scheme": "urn:client:uk:claim", "issuer": "uk-claims"})
    ]


def test_chain_of_two_calls() -> None:
    result = parse_transform_expr(
        "parseDate(fmt='yyyy-MM-dd') -> instantAtStartOfDay(zone='Europe/London')"
    )
    assert result == [
        TransformCall(name="parseDate", args={"fmt": "yyyy-MM-dd"}),
        TransformCall(name="instantAtStartOfDay", args={"zone": "Europe/London"}),
    ]


def test_chain_of_three_calls_is_allowed() -> None:
    result = parse_transform_expr("identity -> identity -> identity")
    assert len(result) == 3


def test_chain_of_four_calls_is_rejected() -> None:
    with pytest.raises(MappingParseError):
        parse_transform_expr("identity -> identity -> identity -> identity")


def test_constant_as_top_level_call_maps_positional_arg_to_const() -> None:
    result = parse_transform_expr('constant("GBP")')
    assert result == [TransformCall(name="constant", args={"const": "GBP"})]


def test_constant_as_nested_argument_resolves_to_literal() -> None:
    result = parse_transform_expr('toMonetaryAmount(currency=constant("GBP"))')
    assert result == [TransformCall(name="toMonetaryAmount", args={"currency": "GBP"})]


def test_positional_argument_rejected_for_non_constant_call() -> None:
    with pytest.raises(MappingParseError):
        parse_transform_expr("scale(0.01)")


def test_single_and_double_quoted_strings_both_accepted() -> None:
    assert parse_transform_expr("valueMap(map='X')")[0].args == {"map": "X"}
    assert parse_transform_expr('valueMap(map="X")')[0].args == {"map": "X"}


def test_integer_and_decimal_literals() -> None:
    assert parse_transform_expr("scale(factor=2)")[0].args == {"factor": 2}
    assert parse_transform_expr("scale(factor=0.01)")[0].args == {"factor": 0.01}


def test_negative_number_literal() -> None:
    assert parse_transform_expr("scale(factor=-1)")[0].args == {"factor": -1}


def test_boolean_literals() -> None:
    assert parse_transform_expr("normaliseCase(mode=true)")[0].args == {"mode": True}
    assert parse_transform_expr("normaliseCase(mode=false)")[0].args == {"mode": False}


def test_bare_unquoted_token_treated_as_string() -> None:
    assert parse_transform_expr("valueMap(map=ClaimStatus.uk)")[0].args == {"map": "ClaimStatus.uk"}


def test_malformed_call_raises() -> None:
    with pytest.raises(MappingParseError):
        parse_transform_expr("not a valid call (")


def test_empty_argument_raises() -> None:
    with pytest.raises(MappingParseError):
        parse_transform_expr("toIdentifier(scheme='x',,issuer='y')")


def test_whitespace_around_calls_is_trimmed() -> None:
    result = parse_transform_expr("  identity  ->  identity  ")
    assert result == [TransformCall(name="identity", args={}), TransformCall(name="identity", args={})]
