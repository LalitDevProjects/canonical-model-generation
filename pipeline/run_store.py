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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C11.JournalEvent._1_0 import C11Journalevent

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TriageEntry:
    """The concrete "triage export" artefact Increment 7 builds (Section
    9.4's emit_review_queue: review-band pairs are "not discarded: they
    become triage input") - NOT the full Section 12.1 run-control API or
    Section 8.4 AWAIT_* checkpoint machinery, which stay out of scope
    this increment (matching Increment 6's own orchestrator-deferral).
    One sink for both the deterministic review queue (kind="review-pair")
    and the Semantic Resolver agent's own AWAIT_TRIAGE escalations
    (kind="agent-escalation")."""

    kind: Literal["review-pair", "agent-escalation"]
    reason: str
    member_attribute_ids: tuple[str, ...]
    score: float | None = None
    features: dict[str, float] | None = None
    cluster_payload: dict[str, object] | None = None


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

    def write_attributes(self, run_id: UUID, region: str, records: list[C5Attributerecord]) -> Path:
        """`run-store/{runId}/S3/attributes/{region}.jsonl` - the storage
        layout's literal path ("C5 records, sharded by region"). A
        single-shot overwrite of the whole shard, matching
        write_corpus_manifest's own "compute everything, write once"
        style - the caller (substrate/ingest.py) accumulates every
        record for a region across an ingest run before calling this
        once per region, rather than this method supporting incremental
        appends itself."""
        stage_dir = self.run_dir(run_id) / "S3" / "attributes"
        stage_dir.mkdir(parents=True, exist_ok=True)
        destination = stage_dir / f"{region}.jsonl"
        lines = (json.dumps(record.model_dump(mode="json"), sort_keys=True) for record in records)
        destination.write_text("\n".join(lines) + ("\n" if records else ""), encoding="utf-8")
        return destination

    def read_attributes(self, run_id: UUID, region: str | None = None) -> list[C5Attributerecord]:
        """region=None reads every region's shard, concatenated."""
        stage_dir = self.run_dir(run_id) / "S3" / "attributes"
        paths = [stage_dir / f"{region}.jsonl"] if region is not None else sorted(stage_dir.glob("*.jsonl"))
        records: list[C5Attributerecord] = []
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    records.append(C5Attributerecord.model_validate(json.loads(line)))
        return records

    def append_journal_event(self, run_id: UUID, event: C11Journalevent) -> Path:
        """`run-store/{runId}/journal.jsonl` - append-only, unlike
        write_attributes: the journal is a genuine incremental event log
        (Section 3.5: "JSON Lines so that a run of several hundred
        thousand events streams rather than loads"), written once per
        event as it happens, not sealed all at once at a stage boundary."""
        path = self.run_dir(run_id) / "journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
        return path

    def append_triage_entry(self, run_id: UUID, entry: TriageEntry) -> Path:
        """`run-store/{runId}/S4/triage.jsonl` - append-only, matching
        append_journal_event's shape: triage entries accumulate both from
        the deterministic review queue and from later Semantic Resolver
        escalations, not computed once and sealed like write_attributes."""
        path = self.run_dir(run_id) / "S4" / "triage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": entry.kind,
            "reason": entry.reason,
            "memberAttributeIds": list(entry.member_attribute_ids),
            "score": entry.score,
            "features": entry.features,
            "clusterPayload": entry.cluster_payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return path

    def read_triage_entries(self, run_id: UUID) -> list[TriageEntry]:
        path = self.run_dir(run_id) / "S4" / "triage.jsonl"
        if not path.exists():
            return []
        entries: list[TriageEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            raw = json.loads(line)
            entries.append(
                TriageEntry(
                    kind=raw["kind"],
                    reason=raw["reason"],
                    member_attribute_ids=tuple(raw["memberAttributeIds"]),
                    score=raw.get("score"),
                    features=raw.get("features"),
                    cluster_payload=raw.get("clusterPayload"),
                )
            )
        return entries

    def next_journal_seq(self, run_id: UUID) -> int:
        """The next monotonically-increasing seq value for this run's
        journal - the existing line count (0 for a run with no journal
        yet). A caller appending its own event supplies this as
        C11Journalevent.seq; not itself atomic against concurrent
        appends, matching this store's existing single-writer-per-run
        scope everywhere else (write_corpus_manifest, write_attributes)."""
        path = self.run_dir(run_id) / "journal.jsonl"
        if not path.exists():
            return 0
        return len(path.read_text(encoding="utf-8").splitlines())
