"""
The egress ledger (Section 5.5): "Hash-chained, append-only. A break in
the chain invalidates the run (I6)." append_ledger_entry() is the spec's
own append_ledger() pseudocode, transcribed as faithfully as possible;
body construction is delegated to contracts.validators.ledger_body so the
function that PRODUCES an entry's hash and check_i6_ledger_chain_unbroken,
which VERIFIES it, are provably the same recipe, not two definitions that
could drift apart.

LedgerStore persists to the spec's own exact path (Section 3.7):
`ledger/{region}/entries.jsonl` - "C3, hash-chained, append-only, WORM."
Mirrors pipeline/run_store.py's RunStore pattern: local-filesystem,
base_path defaults to the repo root, overridable to tmp_path in tests so
no test run ever touches a real ledger/ directory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Sequence
from uuid import UUID

from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry

from contracts.validators import canonical_json_bytes, ledger_body, sign

REPO_ROOT = Path(__file__).resolve().parent.parent


def append_ledger_entry(
    *,
    entry_id: str,
    at: datetime,
    region: str,
    artefact_id: str,
    content_hash: str,
    labels: Sequence[str],
    verdict: str,
    policy_version: int,
    lawful_basis: str,
    approver: str | None,
    run_id: UUID,
    prev_hash: str | None,
    signing_key: bytes,
) -> C3Egressledgerentry:
    """Built via a placeholder-then-recompute step, since ledger_body
    takes an already-constructed entry: validate once with a dummy hash
    to get a schema-valid instance, recompute the real hash from its own
    body, then copy the real hash and signature in."""
    provisional = C3Egressledgerentry.model_validate({
        "entryId": entry_id,
        "at": at.isoformat(),
        "region": region,
        "artefactId": artefact_id,
        "contentHash": content_hash,
        "classification": list(labels),
        "verdict": verdict,
        "policyVersion": policy_version,
        "lawfulBasis": lawful_basis,
        "approver": approver,
        "runId": str(run_id),
        "prevHash": prev_hash,
        "hash": "0" * 64,
        "signature": "",
    })
    entry_hash = hashlib.sha256(canonical_json_bytes(ledger_body(provisional))).hexdigest()
    signature = sign(signing_key, entry_hash)
    return provisional.model_copy(update={"hash": entry_hash, "signature": signature})


class LedgerStore:
    """Local-filesystem persistence rooted at base_path (default:
    ledger/ resolved against the repository root). Pass
    base_path=tmp_path in tests so no test run ever touches a real
    ledger/ directory."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        candidate = Path(base_path) if base_path is not None else Path("ledger")
        self._base_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    def _entries_path(self, region: str) -> Path:
        return self._base_path / region / "entries.jsonl"

    def append(self, entry: C3Egressledgerentry) -> Path:
        """Appends one JSON line - never rewrites or truncates an
        existing file, consistent with the ledger's WORM (write-once-
        read-many) retention model."""
        path = self._entries_path(entry.region.value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
        return path

    def read_all(self, region: str) -> list[C3Egressledgerentry]:
        path = self._entries_path(region)
        if not path.exists():
            return []
        entries = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    entries.append(C3Egressledgerentry.model_validate(json.loads(line)))
        return entries

    def latest_hash(self, region: str) -> str | None:
        """The prevHash a new entry for this region should chain from -
        None if the region has no entries yet (the next entry is that
        region's genesis entry)."""
        entries = self.read_all(region)
        if not entries:
            return None
        return str(entries[-1].hash)
