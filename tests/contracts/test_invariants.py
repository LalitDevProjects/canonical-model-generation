"""
Runs the six cross-artefact invariant checks (contracts/validators.py)
against multi-record bundle fixtures under tests/fixtures/invariants/{i1..i6}/.

Single-document fixtures (tests/contracts/test_fixtures.py) can't exercise
these: each invariant needs more than one record in hand at once (e.g. does
this evidenceRef resolve against the run's actual CorpusManifest), which a
single JSON document can't provide context for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.validators import (
    check_i1_evidence_resolvable,
    check_i2_cluster_members_same_run,
    check_i3_candidate_traces_to_attribute,
    check_i4_coverage_scored_attributes_evidenced,
    check_i5_mapping_entries_have_disposition,
    check_i6_ledger_chain_unbroken,
)
from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C10.MappingSpec._1_0 import C10Mappingspec

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "invariants"


def _cases(invariant: str) -> list[Path]:
    directory = FIXTURES_ROOT / invariant
    return sorted(directory.glob("*.json"))


@pytest.mark.parametrize("path", _cases("i1"), ids=lambda p: p.stem)
def test_i1_evidence_resolvable(path: Path) -> None:
    bundle = json.loads(path.read_text())
    manifest = C4Corpusmanifest.model_validate(bundle["manifest"])
    attributes = [C5Attributerecord.model_validate(a) for a in bundle["attributes"]]
    violations = check_i1_evidence_resolvable(attributes, manifest)
    assert bool(violations) == bundle["expect_violations"], bundle["description"]


@pytest.mark.parametrize("path", _cases("i2"), ids=lambda p: p.stem)
def test_i2_cluster_members_same_run(path: Path) -> None:
    bundle = json.loads(path.read_text())
    clusters = [C6Conceptcluster.model_validate(c) for c in bundle["clusters"]]
    attributes = [C5Attributerecord.model_validate(a) for a in bundle["attributes"]]
    violations = check_i2_cluster_members_same_run(clusters, attributes, bundle["run_id"])
    assert bool(violations) == bundle["expect_violations"], bundle["description"]


@pytest.mark.parametrize("path", _cases("i3"), ids=lambda p: p.stem)
def test_i3_candidate_traces_to_attribute(path: Path) -> None:
    bundle = json.loads(path.read_text())
    candidates = [C8Canonicalcandidate.model_validate(c) for c in bundle["candidates"]]
    clusters = [C6Conceptcluster.model_validate(c) for c in bundle["clusters"]]
    attributes = [C5Attributerecord.model_validate(a) for a in bundle["attributes"]]
    violations = check_i3_candidate_traces_to_attribute(candidates, clusters, attributes)
    assert bool(violations) == bundle["expect_violations"], bundle["description"]


@pytest.mark.parametrize("path", _cases("i4"), ids=lambda p: p.stem)
def test_i4_coverage_scored_attributes_evidenced(path: Path) -> None:
    bundle = json.loads(path.read_text())
    report = C9Coveragereport.model_validate(bundle["report"])
    violations = check_i4_coverage_scored_attributes_evidenced(report, bundle["scored_attributes"])
    assert bool(violations) == bundle["expect_violations"], bundle["description"]


@pytest.mark.parametrize("path", _cases("i5"), ids=lambda p: p.stem)
def test_i5_mapping_entries_have_disposition(path: Path) -> None:
    bundle = json.loads(path.read_text())
    spec = C10Mappingspec.model_validate(bundle["spec"])
    violations = check_i5_mapping_entries_have_disposition(spec)
    assert bool(violations) == bundle["expect_violations"], bundle["description"]


@pytest.mark.parametrize("path", _cases("i6"), ids=lambda p: p.stem)
def test_i6_ledger_chain_unbroken(path: Path) -> None:
    bundle = json.loads(path.read_text())
    entries = [C3Egressledgerentry.model_validate(e) for e in bundle["entries"]]
    violations = check_i6_ledger_chain_unbroken(entries)
    assert bool(violations) == bundle["expect_violations"], bundle["description"]
