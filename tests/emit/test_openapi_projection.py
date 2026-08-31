"""Hermetic tests for emit/openapi.py - the projection carries no inline
type definitions of its own, only $ref pointers to already-emitted
component schemas."""

from __future__ import annotations

import pytest

from emit.openapi import build_openapi_projection

pytestmark = pytest.mark.unit


def test_every_component_is_a_bare_ref() -> None:
    doc = build_openapi_projection(domain="claims", version="1.0", entity_schema_paths={"Claim": "Claim.json", "Incident": "Incident.json"})
    for schema in doc["components"]["schemas"].values():
        assert set(schema) == {"$ref"}


def test_refs_point_at_the_given_paths() -> None:
    doc = build_openapi_projection(domain="claims", version="1.0", entity_schema_paths={"Claim": "Claim.json"})
    assert doc["components"]["schemas"]["Claim"]["$ref"] == "Claim.json"


def test_no_paths_defined() -> None:
    doc = build_openapi_projection(domain="claims", version="1.0", entity_schema_paths={})
    assert doc["paths"] == {}


def test_openapi_version_and_info() -> None:
    doc = build_openapi_projection(domain="claims", version="1.0.0", entity_schema_paths={})
    assert doc["openapi"] == "3.1.0"
    assert doc["info"] == {"title": "claims canonical model", "version": "1.0.0"}
