"""
Run-store persistence (Section 3.7): `run-store/{runId}/...`.

Not a general registry - just enough to write and re-read a sealed stage
output across process boundaries. S1 "Corpus assembly" is a barrier stage
(Section 8.1); later increments read S1's sealed CorpusManifest back rather
than re-running S1, so this needs to exist starting at Increment 2 even
though pipeline/'s own README describes it as "built alongside I2-I9."

The spec's storage layout (Section 3.7) shows `run-store/{runId}/manifest.json`
labelled as C11 RunManifest, but gives no path for C4 CorpusManifest itself.
This writes C4 at `run-store/{runId}/S1/corpus_manifest.json` - distinct
from C11's own manifest.json - following the per-stage-folder convention
(`run-store/{runId}/S1..S8/`) implied elsewhere in the storage layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class RunStore:
    """Local-filesystem persistence rooted at base_path (default:
    run-store/ resolved against the repository root). Pass
    base_path=tmp_path in tests so no test run ever touches a real
    run-store/ directory."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        candidate = Path(base_path) if base_path is not None else Path("run-store")
        self._base_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    def run_dir(self, run_id: UUID) -> Path:
        return self._base_path / str(run_id)

    def write_corpus_manifest(self, run_id: UUID, manifest: C4Corpusmanifest) -> Path:
        stage_dir = self.run_dir(run_id) / "S1"
        stage_dir.mkdir(parents=True, exist_ok=True)
        destination = stage_dir / "corpus_manifest.json"
        destination.write_text(
            json.dumps(manifest.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination

    def read_corpus_manifest(self, run_id: UUID) -> C4Corpusmanifest:
        path = self.run_dir(run_id) / "S1" / "corpus_manifest.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return C4Corpusmanifest.model_validate(raw)
