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

Extended for Section 12's run-control API and pipeline/orchestrator.py:
`write_run_manifest`/`read_run_manifest`/`update_run_state`/`list_runs`
(C11 RunManifest itself was never persisted before, despite this module's
own docstring naming its path since Increment 2), `read_journal_events`
(no read-back for the journal existed before - only append + count),
`write_clusters`/`read_clusters` and `write_candidates`/`read_candidates`
(neither ConceptCluster nor CanonicalCandidate was persisted anywhere
before), and generalised checkpoint sealing/decision recording
(`seal_checkpoint`/`read_sealed_checkpoint`/`write_checkpoint_decisions`/
`read_checkpoint_decisions`/`checkpoint_decisions_complete`), covering
TRIAGE/RATIFY/ARB uniformly - `TriageEntry`'s own `S4/triage.jsonl` stays
exactly as it was for I7's own clustering review queue; checkpoint sealing
is a separate, generic mechanism the orchestrator layers on top of it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C11.JournalEvent._1_0 import C11Journalevent
from generated.C11.RunManifest._1_0 import C11Runmanifest

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

    def _atomic_write_json(self, path: Path, data: object) -> None:
        """Unlike write_corpus_manifest/write_attributes (write-once,
        never re-read while being written), manifest.json and sealed
        checkpoints are re-read repeatedly by a live API server while a
        run is in flight - write to a sibling .tmp file and os.replace
        so a reader never observes a partially-written file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)

    def write_run_manifest(self, run_id: UUID, manifest: C11Runmanifest) -> Path:
        destination = self.run_dir(run_id) / "manifest.json"
        self._atomic_write_json(destination, manifest.model_dump(mode="json"))
        return destination

    def read_run_manifest(self, run_id: UUID) -> C11Runmanifest:
        path = self.run_dir(run_id) / "manifest.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return C11Runmanifest.model_validate(raw)

    def update_run_state(self, run_id: UUID, state: str) -> C11Runmanifest:
        updated = self.read_run_manifest(run_id).model_copy(update={"state": state})
        self.write_run_manifest(run_id, updated)
        return updated

    def list_runs(self, *, domain: str | None = None) -> list[C11Runmanifest]:
        """Every run with a persisted manifest.json, optionally filtered
        by domain - the run-control API's own source for the 409
        run-conflict check ("an active run already exists for this
        domain")."""
        if not self._base_path.exists():
            return []
        manifests: list[C11Runmanifest] = []
        for entry in sorted(self._base_path.iterdir()):
            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = C11Runmanifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
            if domain is not None and manifest.domain != domain:
                continue
            manifests.append(manifest)
        return manifests

    def read_journal_events(
        self, run_id: UUID, *, from_seq: int = 0, limit: int | None = None
    ) -> list[C11Journalevent]:
        path = self.run_dir(run_id) / "journal.jsonl"
        if not path.exists():
            return []
        events: list[C11Journalevent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            raw = json.loads(line)
            if raw.get("seq", 0) < from_seq:
                continue
            events.append(C11Journalevent.model_validate(raw))
            if limit is not None and len(events) >= limit:
                break
        return events

    def write_clusters(self, run_id: UUID, clusters: list[C6Conceptcluster]) -> Path:
        """`run-store/{runId}/S4/clusters.jsonl` - S4's sibling deliverable
        to the existing triage.jsonl (which carries only the review-band
        material, not the confidently-linked clusters run_clustering
        also produces)."""
        stage_dir = self.run_dir(run_id) / "S4"
        stage_dir.mkdir(parents=True, exist_ok=True)
        destination = stage_dir / "clusters.jsonl"
        lines = (json.dumps(c.model_dump(mode="json"), sort_keys=True) for c in clusters)
        destination.write_text("\n".join(lines) + ("\n" if clusters else ""), encoding="utf-8")
        return destination

    def read_clusters(self, run_id: UUID) -> list[C6Conceptcluster]:
        path = self.run_dir(run_id) / "S4" / "clusters.jsonl"
        if not path.exists():
            return []
        return [
            C6Conceptcluster.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def write_candidates(self, run_id: UUID, candidates: list[C8Canonicalcandidate]) -> Path:
        """`run-store/{runId}/S6/candidates.jsonl` - Canonical
        Synthesiser's stage."""
        stage_dir = self.run_dir(run_id) / "S6"
        stage_dir.mkdir(parents=True, exist_ok=True)
        destination = stage_dir / "candidates.jsonl"
        lines = (json.dumps(c.model_dump(mode="json"), sort_keys=True) for c in candidates)
        destination.write_text("\n".join(lines) + ("\n" if candidates else ""), encoding="utf-8")
        return destination

    def read_candidates(self, run_id: UUID) -> list[C8Canonicalcandidate]:
        path = self.run_dir(run_id) / "S6" / "candidates.jsonl"
        if not path.exists():
            return []
        return [
            C8Canonicalcandidate.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def seal_checkpoint(
        self, run_id: UUID, checkpoint: str, *, items: list[dict[str, Any]], corpus_hash: str
    ) -> Path:
        """`run-store/{runId}/checkpoints/{checkpoint}/sealed.json`.
        `corpusHashAtSeal` is the 409 corpus-drift check's own source of
        truth: the run-control API compares it against the run's
        *current* RunManifest.corpusHash at decision-submit time."""
        destination = self.run_dir(run_id) / "checkpoints" / checkpoint / "sealed.json"
        payload = {
            "checkpoint": checkpoint,
            "sealedAt": datetime.now(timezone.utc).isoformat(),
            "payloadRef": f"run-store://{run_id}/checkpoints/{checkpoint}/sealed.json",
            "items": items,
            "corpusHashAtSeal": corpus_hash,
        }
        self._atomic_write_json(destination, payload)
        return destination

    def read_sealed_checkpoint(self, run_id: UUID, checkpoint: str) -> dict[str, Any] | None:
        path = self.run_dir(run_id) / "checkpoints" / checkpoint / "sealed.json"
        if not path.exists():
            return None
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result

    def write_checkpoint_decisions(
        self, run_id: UUID, checkpoint: str, decisions: list[dict[str, Any]], *, complete: bool
    ) -> Path:
        """`run-store/{runId}/checkpoints/{checkpoint}/decisions.jsonl` -
        append-only, one line per POST .../decisions submission batch
        ("Decisions are captured against the candidate at the moment
        they are made", Section 12.4). `complete` reflects the *last*
        submitted batch - the run resumes once a batch sets it true."""
        destination = self.run_dir(run_id) / "checkpoints" / checkpoint / "decisions.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        batch = {
            "decisions": decisions,
            "complete": complete,
            "submittedAt": datetime.now(timezone.utc).isoformat(),
        }
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(batch, sort_keys=True) + "\n")
        return destination

    def read_checkpoint_decisions(self, run_id: UUID, checkpoint: str) -> list[dict[str, Any]]:
        """Every decision across every submitted batch, flattened."""
        path = self.run_dir(run_id) / "checkpoints" / checkpoint / "decisions.jsonl"
        if not path.exists():
            return []
        decisions: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                decisions.extend(json.loads(line)["decisions"])
        return decisions

    def checkpoint_decisions_complete(self, run_id: UUID, checkpoint: str) -> bool:
        path = self.run_dir(run_id) / "checkpoints" / checkpoint / "decisions.jsonl"
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
        return bool(lines) and bool(json.loads(lines[-1]).get("complete"))
