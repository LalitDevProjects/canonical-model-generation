"""
Increment 2's literal acceptance test (Section 17.2): "A run over the
golden corpus produces a sealed manifest whose corpusHash is stable across
repeats, with every excluded artefact carrying a reason."

Uses REAL connectors (GitConnector against a real temp git repo,
ConfluenceConnector against real fixture files) over the REAL golden
corpus under golden/ - not fakes. Every component this test depends on
(relevance filtering, manifest assembly, run-store persistence) is already
independently proven in its own test module; this wires them together.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

from config.settings import load_settings
from connectors.base import ConnectorScope
from connectors.confluence_connector import ConfluenceConnector
from connectors.git_connector import GitConnector
from connectors.manifest import assemble_corpus_manifest
from pipeline.run_store import RunStore

from conftest import GOLDEN_GIT_DIR, manifest_to_schema_json

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"

pytestmark = pytest.mark.e2e


def _fresh_git_repo(tmp_path: Path, name: str) -> Path:
    """Independent copy of golden/git/, its own git history - so two
    manifest-assembly calls in the same test are provably independent
    (no shared object identity/caching could be responsible for equal
    corpusHash values)."""
    repo_path = tmp_path / name
    shutil.copytree(GOLDEN_GIT_DIR, repo_path)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("add", "-A")
    git("commit", "-q", "-m", "golden corpus fixture commit")
    return repo_path


def _registry() -> Registry:
    files = sorted(CONTRACTS_DIR.rglob("*.json"))
    docs = {f: json.loads(f.read_text()) for f in files}
    resources = [(doc.get("$id", str(f)), Resource.from_contents(doc)) for f, doc in docs.items()]
    return Registry().with_resources(resources)


def _assemble(git_repo: Path, confluence_dir: Path) -> C4Corpusmanifest:
    settings = load_settings()
    git_connector = GitConnector(git_repo, region="us")
    confluence_connector = ConfluenceConnector(confluence_dir, region="uk")
    scope = ConnectorScope(region="us", domain="claims")
    return assemble_corpus_manifest(
        run_id=uuid4(),
        domain="claims",
        sources=[(git_connector, scope), (confluence_connector, scope)],
        cfg=settings.relevance,
    )


class TestGoldenCorpusEndToEnd:
    def test_corpus_hash_stable_across_repeats(self, tmp_path: Path, golden_confluence_dir: Path) -> None:
        repo_1 = _fresh_git_repo(tmp_path, "run-1")
        repo_2 = _fresh_git_repo(tmp_path, "run-2")

        manifest_1 = _assemble(repo_1, golden_confluence_dir)
        manifest_2 = _assemble(repo_2, golden_confluence_dir)

        assert manifest_1.corpusHash == manifest_2.corpusHash
        assert manifest_1.runId != manifest_2.runId

    def test_every_excluded_artefact_carries_a_reason(self, tmp_path: Path, golden_confluence_dir: Path) -> None:
        repo = _fresh_git_repo(tmp_path, "run")
        manifest = _assemble(repo, golden_confluence_dir)

        assert len(manifest.exclusions) == 1
        exclusion = manifest.exclusions[0]
        assert "off-domain" in exclusion.uri
        assert exclusion.reason == "out-of-domain"
        assert exclusion.decidedBy == "pass1"
        assert exclusion.detail is not None and exclusion.detail != ""

    def test_kept_artefacts_and_schema_validity(self, tmp_path: Path, golden_confluence_dir: Path) -> None:
        repo = _fresh_git_repo(tmp_path, "run")
        manifest = _assemble(repo, golden_confluence_dir)

        # 3 regional OpenAPI files (git) + 1 Confluence page (uncertain -> kept)
        assert len(manifest.artefacts) == 4
        for artefact in manifest.artefacts:
            assert artefact.sanitisation is not None

        schema = json.loads((CONTRACTS_DIR / "C4" / "CorpusManifest" / "1.0.json").read_text())
        Draft202012Validator(schema, registry=_registry()).validate(manifest_to_schema_json(manifest))

    def test_manifest_round_trips_through_run_store(self, tmp_path: Path, golden_confluence_dir: Path) -> None:
        repo = _fresh_git_repo(tmp_path, "run")
        manifest = _assemble(repo, golden_confluence_dir)

        store = RunStore(base_path=tmp_path / "run-store")
        store.write_corpus_manifest(manifest.runId, manifest)
        reread = store.read_corpus_manifest(manifest.runId)

        assert reread.corpusHash == manifest.corpusHash
        assert len(reread.artefacts) == len(manifest.artefacts)
        assert len(reread.exclusions) == len(manifest.exclusions)
