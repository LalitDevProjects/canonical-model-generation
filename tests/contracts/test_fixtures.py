"""
Validates every fixture under tests/fixtures/contracts/{Cn}/{Name}/{positive,negative}/
against both its JSON Schema (contracts/{Cn}/{Name}/1.0.json) and its
generated Pydantic model (generated/{Cn}/{Name}/_1_0.py).

Both validation paths run for every fixture, not just one, because some
contracts (C7 AlignmentRecord's if/then guardrails, C10 MappingSpec's
transform-xor-disposition oneOf) are enforced by jsonschema but NOT by the
generated Pydantic models alone - see contracts/validators.py's module
docstring. A positive fixture must pass both; a negative fixture is expected
to fail at least one.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "contracts"

# Maps a contract directory name (e.g. "C5/AttributeRecord") to the
# generated module and top-level model class name that represents it.
_CONTRACT_MODEL_MAP: dict[str, tuple[str, str]] = {
    "C1/SourceArtefact": ("generated.C1.SourceArtefact._1_0", "C1Sourceartefact"),
    "C2/SanitisationRecord": ("generated.C2.SanitisationRecord._1_0", "C2Sanitisationrecord"),
    "C3/EgressLedgerEntry": ("generated.C3.EgressLedgerEntry._1_0", "C3Egressledgerentry"),
    "C4/CorpusManifest": ("generated.C4.CorpusManifest._1_0", "C4Corpusmanifest"),
    "C5/AttributeRecord": ("generated.C5.AttributeRecord._1_0", "C5Attributerecord"),
    "C6/ConceptCluster": ("generated.C6.ConceptCluster._1_0", "C6Conceptcluster"),
    "C7/AlignmentRecord": ("generated.C7.AlignmentRecord._1_0", "C7Alignmentrecord"),
    "C8/CanonicalCandidate": ("generated.C8.CanonicalCandidate._1_0", "C8Canonicalcandidate"),
    "C9/CoverageReport": ("generated.C9.CoverageReport._1_0", "C9Coveragereport"),
    "C9/GapEntry": ("generated.C9.GapEntry._1_0", "C9Gapentry"),
    "C10/MappingSpec": ("generated.C10.MappingSpec._1_0", "C10Mappingspec"),
    "C11/RunManifest": ("generated.C11.RunManifest._1_0", "C11Runmanifest"),
    "C11/JournalEvent": ("generated.C11.JournalEvent._1_0", "C11Journalevent"),
}


def _load_registry() -> Registry:
    files = sorted(CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text()) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


_REGISTRY = _load_registry()


def _model_for(contract_id: str) -> type[BaseModel]:
    module_name, class_name = _CONTRACT_MODEL_MAP[contract_id]
    module = importlib.import_module(module_name)
    model: type[BaseModel] = getattr(module, class_name)
    return model


def _schema_for(contract_id: str) -> dict[str, Any]:
    schema_path = CONTRACTS_DIR / contract_id / "1.0.json"
    schema: dict[str, Any] = json.loads(schema_path.read_text())
    return schema


def _collect(kind: str) -> list[tuple[str, Path]]:
    pairs: list[tuple[str, Path]] = []
    for contract_id in _CONTRACT_MODEL_MAP:
        directory = FIXTURES_ROOT / contract_id / kind
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            pairs.append((contract_id, path))
    return pairs


POSITIVE = _collect("positive")
NEGATIVE = _collect("negative")


def test_every_contract_has_at_least_one_positive_and_negative_fixture() -> None:
    positive_contracts = {contract_id for contract_id, _ in POSITIVE}
    negative_contracts = {contract_id for contract_id, _ in NEGATIVE}
    all_contracts = set(_CONTRACT_MODEL_MAP)
    assert positive_contracts == all_contracts, f"missing positive fixtures for {all_contracts - positive_contracts}"
    assert negative_contracts == all_contracts, f"missing negative fixtures for {all_contracts - negative_contracts}"


@pytest.mark.parametrize("contract_id,path", POSITIVE, ids=[str(p) for _, p in POSITIVE])
def test_positive_fixture_validates(contract_id: str, path: Path) -> None:
    instance = json.loads(path.read_text())
    schema = _schema_for(contract_id)

    Draft202012Validator(schema, registry=_REGISTRY).validate(instance)

    model = _model_for(contract_id)
    model.model_validate(instance)


@pytest.mark.parametrize("contract_id,path", NEGATIVE, ids=[str(p) for _, p in NEGATIVE])
def test_negative_fixture_is_rejected(contract_id: str, path: Path) -> None:
    instance = json.loads(path.read_text())
    schema = _schema_for(contract_id)

    schema_errors = list(Draft202012Validator(schema, registry=_REGISTRY).iter_errors(instance))

    pydantic_rejected = False
    if not schema_errors:
        model = _model_for(contract_id)
        try:
            model.model_validate(instance)
        except ValidationError:
            pydantic_rejected = True

    assert schema_errors or pydantic_rejected, (
        f"negative fixture {path} was accepted by BOTH jsonschema and Pydantic; "
        "it isn't actually exercising an invalid case"
    )
