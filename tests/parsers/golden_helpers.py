from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact

GOLDEN_ROOT = Path(__file__).resolve().parents[2] / "golden"
GOLDEN_GIT_DIR = GOLDEN_ROOT / "git"
GOLDEN_XSD_DIR = GOLDEN_ROOT / "xsd"
GOLDEN_WSDL_DIR = GOLDEN_ROOT / "wsdl"
GOLDEN_AVRO_DIR = GOLDEN_ROOT / "avro"


def golden_xsd(relative_path: str) -> bytes:
    return (GOLDEN_XSD_DIR / relative_path).read_bytes()


def golden_wsdl(relative_path: str) -> bytes:
    return (GOLDEN_WSDL_DIR / relative_path).read_bytes()


def golden_avro(relative_path: str) -> bytes:
    return (GOLDEN_AVRO_DIR / relative_path).read_bytes()


def golden_git(relative_path: str) -> bytes:
    return (GOLDEN_GIT_DIR / relative_path).read_bytes()


def build_golden_git_repo(tmp_path: Path) -> Path:
    """Copies golden/git/ into tmp_path and turns it into a real git
    repository with one commit - the same construction
    tests/connectors/conftest.py's golden_git_repo fixture uses, kept as a
    small, directly-importable duplicate here rather than reaching across
    a sibling test-package boundary (tests/ has no __init__.py anywhere,
    so pytest's prepend import mode only puts each test directory itself
    on sys.path, not its siblings)."""
    repo_path = tmp_path / "golden-repo"
    shutil.copytree(GOLDEN_GIT_DIR, repo_path)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
        ["add", "-A"],
        ["commit", "-q", "-m", "golden corpus fixture commit"],
    ):
        subprocess.run(["git", *args], cwd=repo_path, check=True, capture_output=True)
    return repo_path


def make_source_artefact(
    media_type: str,
    region: str = "us",
    artefact_id: str = "test-artefact",
    system: str = "git",
) -> C1Sourceartefact:
    return C1Sourceartefact.model_validate({
        "artefactId": artefact_id,
        "region": region,
        "system": system,
        "uri": f"{system}://example/{artefact_id}",
        "version": "abc1234",
        "contentHash": "a" * 64,
        "mediaType": media_type,
        "evidenceTier": 1,
        "sanitisation": {
            "artefactId": artefact_id,
            "contentHash": "a" * 64,
            "labels": ["STRUCTURAL"],
            "verdict": "allow",
            "licenceDisposition": "permitted",
            "policyVersion": 1,
            "classifiedAt": "2026-08-20T09:00:00Z",
        },
    })
