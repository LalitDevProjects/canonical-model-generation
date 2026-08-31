from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from config.settings import RelevanceConfig
from connectors.base import ArtefactRef, Connector, ConnectorScope, HealthStatus, RawArtefact
from connectors.manifest import (
    _artefact_id_for,
    _placeholder_sanitisation,
    assemble_corpus_manifest,
    canonical_json_bytes,
    compute_corpus_hash,
)
from conftest import manifest_to_schema_json

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"


class FakeConnector(Connector):
    """A lightweight test double - no real git/Confluence I/O - so
    manifest-assembly logic is proven independent of real connector
    behaviour (already covered separately by test_git_connector.py /
    test_confluence_connector.py)."""

    def __init__(self, system: str, refs: list[ArtefactRef], content_by_uri: dict[str, bytes]) -> None:
        self.system = system
        self._refs = refs
        self._content_by_uri = content_by_uri

    def discover(self, scope: ConnectorScope) -> Iterator[ArtefactRef]:
        yield from self._refs

    def fetch(self, ref: ArtefactRef) -> RawArtefact:
        return RawArtefact(
            uri=ref.uri, version="v1", content=self._content_by_uri[ref.uri],
            media_type=ref.media_type, owning_team=None, metadata={},
        )

    def health(self) -> HealthStatus:
        return HealthStatus(system=self.system, ok=True)


def _cfg() -> RelevanceConfig:
    return RelevanceConfig.model_validate({
        "pass1_keep": 0.65,
        "pass1_drop": 0.20,
        "domain_tokens": {"claims": ["claim"]},
        "pass1_weights": {"path": 0.60, "catalogue": 0.20, "gateway": 0.10, "kind": 0.10},
        "contract_media_types": ["application/yaml"],
    })


class TestCanonicalJsonBytes:
    def test_sorted_keys_no_whitespace(self) -> None:
        assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


class TestComputeCorpusHash:
    def test_deterministic_and_order_independent(self) -> None:
        h1 = compute_corpus_hash(["bbb", "aaa", "ccc"])
        h2 = compute_corpus_hash(["ccc", "aaa", "bbb"])
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_gives_different_hash(self) -> None:
        assert compute_corpus_hash(["aaa"]) != compute_corpus_hash(["bbb"])

    def test_empty_list_is_stable(self) -> None:
        assert compute_corpus_hash([]) == compute_corpus_hash([])


class TestArtefactIdFor:
    def test_deterministic_for_same_ref_fields(self) -> None:
        ref = ArtefactRef(uri="git://repo/a.yaml", system="git", region="us", media_type="application/yaml")
        assert _artefact_id_for(ref) == _artefact_id_for(ref)

    def test_differs_by_uri(self) -> None:
        ref_a = ArtefactRef(uri="git://repo/a.yaml", system="git", region="us", media_type="application/yaml")
        ref_b = ArtefactRef(uri="git://repo/b.yaml", system="git", region="us", media_type="application/yaml")
        assert _artefact_id_for(ref_a) != _artefact_id_for(ref_b)


class TestPlaceholderSanitisation:
    def test_validates_against_c2_schema(self) -> None:
        from datetime import datetime, timezone

        record = _placeholder_sanitisation("art-1", "a" * 64, datetime.now(timezone.utc))
        schema = json.loads((CONTRACTS_DIR / "C2" / "SanitisationRecord" / "1.0.json").read_text())
        registry = _registry()
        Draft202012Validator(schema, registry=registry).validate(manifest_to_schema_json(record))


def _registry() -> Registry:
    files = sorted(CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text()) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


class TestAssembleCorpusManifest:
    def test_produces_schema_valid_manifest_with_keep_and_drop(self) -> None:
        keep_ref = ArtefactRef(uri="git://repo/claims-us/openapi.yaml", system="git", region="us", media_type="application/yaml")
        drop_ref = ArtefactRef(uri="git://repo/off-domain/menu.yaml", system="git", region="us", media_type="application/yaml")
        connector = FakeConnector("git", [keep_ref, drop_ref], {
            keep_ref.uri: b"keep content",
            drop_ref.uri: b"drop content",
        })

        manifest = assemble_corpus_manifest(
            run_id=uuid4(), domain="claims",
            sources=[(connector, ConnectorScope(region="us", domain="claims"))],
            cfg=_cfg(),
        )

        assert len(manifest.artefacts) == 1
        assert manifest.artefacts[0].uri == keep_ref.uri
        assert len(manifest.exclusions) == 1
        assert manifest.exclusions[0].uri == drop_ref.uri
        assert manifest.exclusions[0].reason == "out-of-domain"

        schema = json.loads((CONTRACTS_DIR / "C4" / "CorpusManifest" / "1.0.json").read_text())
        Draft202012Validator(schema, registry=_registry()).validate(manifest_to_schema_json(manifest))

    def test_corpus_hash_stable_across_two_independent_calls(self) -> None:
        keep_ref = ArtefactRef(uri="git://repo/claims-us/openapi.yaml", system="git", region="us", media_type="application/yaml")
        connector = FakeConnector("git", [keep_ref], {keep_ref.uri: b"stable content"})
        cfg = _cfg()

        manifest_1 = assemble_corpus_manifest(
            run_id=uuid4(), domain="claims",
            sources=[(connector, ConnectorScope(region="us", domain="claims"))], cfg=cfg,
        )
        manifest_2 = assemble_corpus_manifest(
            run_id=uuid4(), domain="claims",
            sources=[(connector, ConnectorScope(region="us", domain="claims"))], cfg=cfg,
        )

        assert manifest_1.corpusHash == manifest_2.corpusHash
        assert manifest_1.runId != manifest_2.runId  # expected to differ - see manifest.py docstring

    def test_excluded_artefact_is_never_fetched(self) -> None:
        drop_ref = ArtefactRef(uri="git://repo/off-domain/menu.yaml", system="git", region="us", media_type="application/yaml")

        class FailOnFetch(FakeConnector):
            def fetch(self, ref: ArtefactRef) -> RawArtefact:
                raise AssertionError("fetch() must not be called for an excluded ref")

        connector = FailOnFetch("git", [drop_ref], {})
        manifest = assemble_corpus_manifest(
            run_id=uuid4(), domain="claims",
            sources=[(connector, ConnectorScope(region="us", domain="claims"))], cfg=_cfg(),
        )
        assert manifest.artefacts == []
        assert len(manifest.exclusions) == 1
