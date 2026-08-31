"""Hermetic tests for emit/logical_model.py - the JSON-LD export, real
lineage in both directions (realisedBy/derivedFrom), and the honest
alignment/ratification substitutions this module documents."""

from __future__ import annotations

import pytest
from emit_builders import alignment, candidate

from emit.logical_model import build_logical_model

pytestmark = pytest.mark.unit


def test_entities_grouped_and_sorted() -> None:
    model = build_logical_model(
        [candidate(entity="Claim"), candidate(entity="Incident", attribute="occurrenceDateTime")],
        domain="claims", version="1.0", entity_schema_paths={},
    )
    assert [e["label"] for e in model["entities"]] == ["Claim", "Incident"]


def test_attribute_carries_realised_by_pointer() -> None:
    model = build_logical_model([candidate()], domain="claims", version="1.0", entity_schema_paths={"Claim": "Claim.json"})
    attr = model["entities"][0]["attributes"][0]
    assert attr["realisedBy"] == "Claim.json#/properties/claimId"


def test_attribute_carries_derived_from_when_evidence_supplied() -> None:
    evref = "evref://uk/git/x@" + "a" * 16 + "#/y"
    model = build_logical_model(
        [candidate()], domain="claims", version="1.0", entity_schema_paths={},
        evidence_by_candidate={"canon://Claim.claimId": [evref]},
    )
    assert model["entities"][0]["attributes"][0]["derivedFrom"] == [evref]


def test_no_derived_from_when_evidence_not_supplied() -> None:
    model = build_logical_model([candidate()], domain="claims", version="1.0", entity_schema_paths={})
    assert "derivedFrom" not in model["entities"][0]["attributes"][0]


def test_ratified_by_present_only_when_approved() -> None:
    model = build_logical_model(
        [candidate(ratification_status="approved", sme="Jane", decided_at="2026-01-01T00:00:00Z")],
        domain="claims", version="1.0", entity_schema_paths={},
    )
    ratified = model["entities"][0]["attributes"][0]["ratifiedBy"]
    assert ratified["sme"] == "Jane"
    assert ratified["session"] == "2026-01-01T00:00:00+00:00"


def test_no_ratified_by_when_pending() -> None:
    model = build_logical_model(
        [candidate(ratification_status="pending", sme=None, decided_at=None)],
        domain="claims", version="1.0", entity_schema_paths={},
    )
    assert "ratifiedBy" not in model["entities"][0]["attributes"][0]


def test_acord_alignment_attached_when_supplied() -> None:
    record = alignment(verdict="unassessed")
    model = build_logical_model(
        [candidate()], domain="claims", version="1.0", entity_schema_paths={},
        alignment_by_entity={"Claim": record},
    )
    assert model["entities"][0]["acordAlignment"] == {"verdict": "unassessed"}


def test_acord_alignment_omitted_when_not_supplied() -> None:
    model = build_logical_model([candidate()], domain="claims", version="1.0", entity_schema_paths={})
    assert "acordAlignment" not in model["entities"][0]


def test_fit_verdict_includes_ref_and_deviation() -> None:
    from generated.C7.AlignmentRecord._1_0 import C7Alignmentrecord

    record = C7Alignmentrecord.model_validate({
        "clusterId": "cluster://x", "acordRef": "acord://information-model/Loss", "verdict": "partial",
        "deviation": "Syndicate scope excludes catastrophe aggregation.",
        "rationale": "x", "evidenceRefs": ["evref://uk/git/x@" + "a" * 16 + "#/y"],
    })
    model = build_logical_model(
        [candidate()], domain="claims", version="1.0", entity_schema_paths={},
        alignment_by_entity={"Claim": record},
    )
    assert model["entities"][0]["acordAlignment"] == {
        "ref": "acord://information-model/Loss",
        "verdict": "partial",
        "deviation": "Syndicate scope excludes catastrophe aggregation.",
    }


def test_definition_included_when_supplied() -> None:
    model = build_logical_model(
        [candidate()], domain="claims", version="1.0", entity_schema_paths={},
        entity_definitions={"Claim": "A claim against a policy."},
    )
    assert model["entities"][0]["definition"] == "A claim against a policy."


def test_context_and_id() -> None:
    model = build_logical_model([], domain="claims", version="1.0", entity_schema_paths={})
    assert model["@context"] == "https://canonicalmodel.internal/canonical/context/1.0.jsonld"
    assert model["@id"] == "logical:claims/1.0"
    assert model["entities"] == []
