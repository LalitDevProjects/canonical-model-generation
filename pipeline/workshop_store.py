"""
File-based persistence for Section 12.4's Workshop and decision API -
workshop records and the decisions captured against them. Mirrors
pipeline/run_store.py's own established directory-per-key convention.

Deliberately does NOT duplicate pack-writing logic: `pack_dir(workshop_id)`
is handed directly to `emit.workshop_pack.assemble_pack(output_dir=...)`,
which already writes every pack file - including its own
`workshop-pack-manifest.json` - for real; `read_pack_manifest` just reads
that back. Reinventing that write path here would be the exact kind of
duplicated pack-building logic the plan calls out to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from emit.workshop_pack import PackFile, WorkshopPackManifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class WorkshopStore:
    """Local-filesystem persistence rooted at base_path (default:
    workshop-store/ resolved against the repository root). Pass
    base_path=tmp_path in tests, matching RunStore's own convention."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        candidate = Path(base_path) if base_path is not None else Path("workshop-store")
        self._base_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    def workshop_dir(self, workshop_id: UUID) -> Path:
        return self._base_path / str(workshop_id)

    def pack_dir(self, workshop_id: UUID) -> Path:
        """Pass this to emit.workshop_pack.assemble_pack(output_dir=...)
        - the real pack files (including workshop-pack-manifest.json)
        are written there directly by that function, not by this store."""
        return self.workshop_dir(workshop_id) / "pack"

    def write_workshop(self, workshop_id: UUID, record: dict[str, Any]) -> Path:
        workshop_dir = self.workshop_dir(workshop_id)
        workshop_dir.mkdir(parents=True, exist_ok=True)
        destination = workshop_dir / "workshop.json"
        destination.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return destination

    def read_workshop(self, workshop_id: UUID) -> dict[str, Any]:
        path = self.workshop_dir(workshop_id) / "workshop.json"
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return raw

    def read_pack_manifest(self, workshop_id: UUID) -> WorkshopPackManifest:
        path = self.pack_dir(workshop_id) / "workshop-pack-manifest.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return WorkshopPackManifest(
            domain=raw["domain"],
            version=raw["version"],
            files=[
                PackFile(path=f["path"], sha256=f["sha256"], description=f["description"])
                for f in raw["files"]
            ],
            declared_losses=raw["declaredLosses"],
        )

    def append_decisions(self, workshop_id: UUID, decisions: list[dict[str, Any]]) -> Path:
        """`{workshopId}/decisions.jsonl` - append-only, one line per
        decision: "captured against the candidate at the moment they are
        made - never reconstructed from minutes afterwards" (Section
        12.4's own quoted rule)."""
        destination = self.workshop_dir(workshop_id) / "decisions.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            for decision in decisions:
                handle.write(json.dumps(decision, sort_keys=True) + "\n")
        return destination

    def read_decisions(self, workshop_id: UUID) -> list[dict[str, Any]]:
        path = self.workshop_dir(workshop_id) / "decisions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
