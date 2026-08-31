from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

GOLDEN_GIT_DIR = Path(__file__).resolve().parents[2] / "golden" / "git"
GOLDEN_CONFLUENCE_DIR = Path(__file__).resolve().parents[2] / "golden" / "confluence"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def golden_git_repo(tmp_path: Path) -> Path:
    """Copies golden/git/ into a temporary directory and turns it into a
    real git repository with one commit, so GitConnector is exercised
    against real git plumbing (a real commit SHA, real `git show`) rather
    than a fake. Local (not global) git identity is configured so this
    works on a clean CI runner with no git config of its own."""
    repo_path = tmp_path / "golden-repo"
    shutil.copytree(GOLDEN_GIT_DIR, repo_path)
    _git("init", "-q", cwd=repo_path)
    _git("config", "user.email", "test@example.invalid", cwd=repo_path)
    _git("config", "user.name", "Test", cwd=repo_path)
    _git("add", "-A", cwd=repo_path)
    _git("commit", "-q", "-m", "golden corpus fixture commit", cwd=repo_path)
    return repo_path


@pytest.fixture
def golden_confluence_dir() -> Path:
    return GOLDEN_CONFLUENCE_DIR


def manifest_to_schema_json(model: BaseModel) -> dict[str, object]:
    """Serialize a C1/C2/C4 model for jsonschema validation.

    Plain model.model_dump(mode="json") is NOT safe here: Pydantic always
    includes every field, so an unset *optional* field (e.g. C1
    SourceArtefact.owningTeam, typed `str | None = None`) comes out as an
    explicit `null` - but the JSON Schema for a merely-optional,
    non-nullable property only declares `"type": "string"`, not
    `["string", "null"]` (optional in JSON Schema means the key may be
    ABSENT, not that it may hold null). exclude_none=True restores
    "absent" as the representation of "not set."

    SCOPE WARNING, do not reuse this blindly on other contracts: this is
    only safe where no *required* field is legitimately nullable.
    C1/C2/C4 (what connectors/manifest.py produces) have no such field.
    C7 AlignmentRecord is a counter-example - its `deviation`/`acordRef`
    are REQUIRED but nullable (the if/then guardrails need the key
    present with an explicit null for e.g. a "fit" verdict); calling
    exclude_none=True on a C7 instance would illegally drop a required
    key. If a future increment needs this for a contract with a
    required-nullable field, dump with exclude_none=False and construct
    the JSON directly instead.
    """
    return model.model_dump(mode="json", exclude_none=True)
