"""
A real, hermetic driving orchestrator for Section 12's run-control API.
No S1-S8 state machine existed anywhere in this repo before this module -
`agents/base.py::route()` remains an identity stub, and Section 8.3's own
pseudocode is an AWS Step Functions definition this repo has no
infrastructure to run. This module does not attempt that. It drives a run
synchronously, in-process, through exactly the stages that are already
real and already deterministic - no live Postgres, no live Anthropic key
required - then stops at a real, sealed TRIAGE checkpoint. Continuing
past that checkpoint into the agent-mediated stages is optional and only
happens when a real model provider is actually configured; otherwise the
run stops there, honestly labelled, never faking a decision.

`create_run()` chains, in order: S1 (real GitConnector instances over
golden/git/claims-{us,uk,eu}/, sealed via connectors.manifest.
assemble_corpus_manifest - the exact same real path
tests/connectors/test_golden_corpus_e2e.py already proves), S3 (real
parsers.router.parse + algorithms.profiling.profile per artefact - NOT
substrate.ingest.ingest_artefacts, which needs a live SubstrateDb
connection for the separate, DB-backed chunking/embedding/graph-write
concern Increment 5 owns), S4 (real algorithms.clustering.run_clustering,
"zero LLM dependency" by its own Increment 7 design). Only domain="claims"
is wired to real golden-corpus data, mirroring how every increment's own
acceptance test relies on the golden corpus as this PoC's own real data.

`resume_after_checkpoint()` requires the checkpoint's decisions to be
complete and the corpus hash unchanged since sealing (the actual 409
corpus-drift check lives here; api/run_control.py translates the
resulting exception to an HTTP 409). Its own continuation covers ACORD
Aligner (degrades automatically - licence disposition is never
"permitted" in this repo, no code change needed), Canonical Synthesiser,
and real coverage/gap computation, over S4's own confidently-linked
clusters.

Two things are deliberately NOT part of this automatic continuation, for
two different reasons. Mapping generation: assembling the
region_records/canonical_model/cluster_map inputs agents.mapping_
generator needs has no natural home in a run-scoped continuation and
stays a manually-invoked path, unchanged. Semantic Resolver (review-band
adjudication): discovered empirically while wiring this module, not
assumed - agents/semantic_resolver.py's own assemble_context() calls
SubstrateApi.search(), which genuinely needs a live SubstrateDb
connection (hybrid BM25+vector retrieval, Increment 5's own DB-backed
concern), unlike ACORD Aligner's acord_lookup() and Canonical
Synthesiser's get_attribute(), neither of which ever touches the
database. Gating the whole continuation on "a live Postgres, if the
review band happens to be non-empty" would contradict this module's own
"model-provider-gated, not also DB-gated" design; review-band material
is therefore left exactly where create_run() sealed it - real, sealed
TRIAGE items - for a caller with real DB access to resolve through the
existing agents.semantic_resolver.make_semantic_resolver_adjudicator
factory directly, outside this orchestrator.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C11.JournalEvent._1_0 import C11Journalevent
from generated.C11.RunManifest._1_0 import C11Runmanifest, Pins

from agents.acord_aligner import align_or_degrade
from agents.base import RunContext
from agents.canonical_synthesiser import make_canonical_synthesiser_factory
from agents.model_gateway import Budget as GatewayBudget
from agents.model_gateway import ModelGateway
from agents.validation import GuardrailViolation
from algorithms.clustering import ReviewPair, run_clustering, write_triage_export
from algorithms.coverage import build_universe, coverage, gap_register
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import PlatformSettings
from connectors.base import ConnectorScope
from connectors.git_connector import GitConnector
from connectors.manifest import assemble_corpus_manifest, compute_corpus_hash
from contracts.validators import unwrap_ref
from gate.evidence_store import EvidenceStore
from gate.ledger import LedgerStore
from gate.policy import load_policy_document
from parsers.router import parse
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from tools.gateway import ToolGateway

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_GIT_DIR = REPO_ROOT / "golden" / "git"
_HERMETIC_DOMAINS = {"claims"}
_REGIONS = ("us", "uk", "eu")

# Real prompt versions pinned by this session's own build - matching
# ctx.pins.prompts.get(agent_id, "1.0.0")'s own lookup in agents/base.py.
_PROMPT_PINS = {
    "semantic-resolver": "2.3.0",
    "acord-aligner": "1.6.0",
    "canonical-synthesiser": "1.9.1",
}


class OrchestratorError(Exception):
    """Base class for every error this module raises."""


class UnsupportedDomainError(OrchestratorError):
    """Raised when create_run() is asked to drive a domain with no real,
    hermetically-wired golden-corpus data. api/run_control.py maps this
    to a 400 invalid-contract response."""


class CheckpointNotSealedError(OrchestratorError):
    """resume_after_checkpoint() called before the named checkpoint was
    ever sealed."""


class CheckpointNotCompleteError(OrchestratorError):
    """resume_after_checkpoint() called before a decisions batch with
    complete=true was submitted."""


class CorpusDriftDetected(OrchestratorError):
    """The run's current corpusHash no longer matches the hash recorded
    when the checkpoint was sealed - Section 12.2's own 409 corpus-drift
    check. api/run_control.py maps this to an HTTP 409."""


def _journal(
    run_store: RunStore, run_id: UUID, *, stage: str, outcome: str, detail: str | None = None
) -> None:
    payload: dict[str, Any] = {
        "runId": str(run_id),
        "seq": run_store.next_journal_seq(run_id),
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "stage.transition",
        "stage": stage,
        "outcome": outcome,
    }
    if detail is not None:
        payload["detail"] = detail
    run_store.append_journal_event(run_id, C11Journalevent.model_validate(payload))


def _stage_git_repo(source_dir: Path, dest_dir: Path) -> Path:
    """A real, independent temp git repository per region - the same
    real-git-plumbing pattern tests/connectors/test_golden_corpus_e2e.py's
    own _fresh_git_repo helper uses, promoted to production code."""
    shutil.copytree(source_dir, dest_dir)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=dest_dir, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "orchestrator@canonicalmodel.internal")
    git("config", "user.name", "Canonical Model Orchestrator")
    git("add", "-A")
    git("commit", "-q", "-m", "golden corpus snapshot")
    return dest_dir


def _profile_records(records: Sequence[C5Attributerecord]) -> list[ProfiledAttribute]:
    """Siblings are scoped to one artefact's own parse output (Section
    9.1's profile(rec, siblings) is called once per artefact's parse in
    a real pipeline), matching tests/algorithms/test_clustering_
    acceptance.py's own real per-artefact grouping - never merged across
    artefacts or regions."""
    by_parent: dict[str | None, list[C5Attributerecord]] = defaultdict(list)
    for record in records:
        by_parent[record.parentPath].append(record)
    profiled: list[ProfiledAttribute] = []
    for record in records:
        siblings = [s for s in by_parent[record.parentPath] if s.attributeId != record.attributeId]
        profiled.append(profile(record, siblings=siblings))
    return profiled


def create_run(
    *,
    domain: str,
    trigger: dict[str, Any],
    pins: dict[str, Any] | None,
    parameters: dict[str, Any] | None,
    budget: dict[str, Any] | None,
    previous_run_id: UUID | None,
    settings: PlatformSettings,
    run_store: RunStore,
    evidence_store: EvidenceStore | None = None,
    ledger_store: LedgerStore | None = None,
    golden_git_dir: Path = GOLDEN_GIT_DIR,
) -> C11Runmanifest:
    if domain not in _HERMETIC_DOMAINS:
        raise UnsupportedDomainError(
            f"domain {domain!r} has no wired real data source; only {sorted(_HERMETIC_DOMAINS)} are"
        )

    run_id = uuid4()
    evidence_store = evidence_store or EvidenceStore()
    ledger_store = ledger_store or LedgerStore()

    initial_manifest = C11Runmanifest.model_validate({
        "runId": str(run_id),
        "domain": domain,
        "trigger": trigger,
        "corpusHash": "0" * 64,
        "pins": pins or {"prompts": {}, "models": {}, "tools": {}, "algorithms": {}},
        "parameters": parameters or {},
        "budget": budget or {"tokensTotal": 1_000_000, "costCeilingGbp": 100.0, "perStage": {}},
        "previousRunId": str(previous_run_id) if previous_run_id is not None else None,
        "state": "CREATED",
        "createdBy": trigger.get("requestedBy", "unknown"),
    })
    run_store.write_run_manifest(run_id, initial_manifest)

    # --- S1: corpus assembly, one real GitConnector per region -----------
    #
    # assemble_corpus_manifest's own connectors_by_system dict is keyed
    # by Connector.system alone (connectors/manifest.py) - every
    # GitConnector reports system="git" regardless of the region it was
    # constructed with, so passing three region-tagged GitConnectors as
    # one combined `sources` list makes the LAST one silently shadow the
    # other two for every fetch() call (discovered empirically: fetching
    # a US-discovered ref against the EU connector's own repo path fails
    # with a real git error). Three independent assemble_corpus_manifest
    # calls - one connector each, no collision - avoids this; their
    # results are merged into one C4Corpusmanifest afterward, with
    # corpusHash recomputed over the real, combined artefact set exactly
    # as compute_corpus_hash defines it.
    policy = load_policy_document(expected_version=settings.egress.policy_version)
    region_manifests: list[C4Corpusmanifest] = []
    for region in _REGIONS:
        with tempfile.TemporaryDirectory(prefix=f"orchestrator-corpus-{region}-") as staging:
            # The staged repo's own directory name becomes the "repo
            # name" component of GitConnector's own uri=git://{name}/...
            # - it MUST keep the "claims-{region}" name real relevance
            # filtering already expects (config/platform.yaml's
            # relevance.domain_tokens), not a bare region code, or every
            # artefact scores as out-of-domain and gets excluded before
            # parsing ever runs.
            region_repo = _stage_git_repo(golden_git_dir / f"claims-{region}", Path(staging) / f"claims-{region}")
            region_manifests.append(
                assemble_corpus_manifest(
                    run_id=run_id,
                    domain=domain,
                    sources=[(GitConnector(region_repo, region=region), ConnectorScope(region=region, domain=domain))],
                    cfg=settings.relevance,
                    egress_cfg=settings.egress,
                    policy=policy,
                    feature_flags=settings.feature_flags,
                    ledger_store=ledger_store,
                    evidence_store=evidence_store,
                )
            )

    all_artefacts = [artefact for m in region_manifests for artefact in m.artefacts]
    all_exclusions = [exclusion for m in region_manifests for exclusion in m.exclusions]
    corpus_manifest = C4Corpusmanifest(
        runId=run_id,
        domain=domain,
        sealedAt=datetime.now(timezone.utc),
        corpusHash=compute_corpus_hash([artefact.contentHash for artefact in all_artefacts]),
        artefacts=all_artefacts,
        exclusions=all_exclusions,
    )
    run_store.write_corpus_manifest(run_id, corpus_manifest)
    run_store.write_run_manifest(
        run_id, initial_manifest.model_copy(update={"corpusHash": corpus_manifest.corpusHash, "state": "RUNNING"})
    )
    _journal(run_store, run_id, stage="S1", outcome="ok", detail=f"{len(corpus_manifest.artefacts)} artefact(s) admitted")

    # --- S3: parsing to IR, one real parse+profile per artefact ----------
    profiled_all: list[ProfiledAttribute] = []
    records_by_region: dict[str, list[C5Attributerecord]] = defaultdict(list)
    for artefact in corpus_manifest.artefacts:
        content = evidence_store.read_artefact(artefact.contentHash)
        records = parse(content, artefact, run_id)
        records_by_region[artefact.region.value].extend(records)
        profiled_all.extend(_profile_records(records))
    for region, records in records_by_region.items():
        run_store.write_attributes(run_id, region, records)
    _journal(run_store, run_id, stage="S3", outcome="ok", detail=f"{len(profiled_all)} attribute(s) profiled")

    # --- S4: deterministic clustering, zero LLM dependency ----------------
    clusters, review_pairs = run_clustering(
        profiled_all,
        run_id=str(run_id),
        api=None,
        config=settings.clustering,
        embed_dimensions=settings.models.embedding_dimensions,
    )
    run_store.write_clusters(run_id, clusters)
    write_triage_export(run_store, run_id, review_pairs)
    _journal(
        run_store, run_id, stage="S4", outcome="ok",
        detail=f"{len(clusters)} cluster(s), {len(review_pairs)} review-band pair(s)",
    )

    # --- seal TRIAGE and stop -----------------------------------------------
    items = [
        {
            "itemId": f"{pair.a.record.attributeId}|{pair.b.record.attributeId}",
            "score": pair.score,
            "reason": f"similarity score {pair.score:.3f} in the review band; not auto-linked",
        }
        for pair in review_pairs
    ]
    run_store.seal_checkpoint(run_id, "TRIAGE", items=items, corpus_hash=corpus_manifest.corpusHash)
    final_manifest = run_store.update_run_state(run_id, "AWAIT_TRIAGE")
    _journal(run_store, run_id, stage="S4", outcome="ok", detail="TRIAGE checkpoint sealed")
    return final_manifest


def _rebuild_profiled(run_store: RunStore, run_id: UUID) -> list[ProfiledAttribute]:
    """Reconstructs ProfiledAttribute objects from persisted C5
    AttributeRecords, region by region - a close approximation of
    create_run()'s own per-artefact sibling grouping, exact for this
    golden fixture's real one-artefact-per-region shape."""
    profiled: list[ProfiledAttribute] = []
    for region in _REGIONS:
        profiled.extend(_profile_records(run_store.read_attributes(run_id, region)))
    return profiled


def _rebuild_review_pairs(run_store: RunStore, run_id: UUID) -> list[ReviewPair]:
    profiled_by_id = {p.record.attributeId: p for p in _rebuild_profiled(run_store, run_id)}
    pairs: list[ReviewPair] = []
    for entry in run_store.read_triage_entries(run_id):
        if entry.kind != "review-pair":
            continue
        a_id, b_id = entry.member_attribute_ids
        if a_id in profiled_by_id and b_id in profiled_by_id:
            pairs.append(
                ReviewPair(a=profiled_by_id[a_id], b=profiled_by_id[b_id], score=entry.score or 0.0, features=entry.features or {})
            )
    return pairs


def _build_run_context(
    run_id: UUID, run_store: RunStore, settings: PlatformSettings, model_gateway: ModelGateway, manifest: C11Runmanifest
) -> RunContext:
    """The three agents this continuation calls (Semantic Resolver, ACORD
    Aligner, Canonical Synthesiser) only ever call
    SubstrateApi.get_attribute/acord_lookup, neither of which touches the
    injected SubstrateDb - get_attribute reads run_store directly, and
    acord_lookup always returns [] regardless (ACORD data is permanently
    unavailable). A SubstrateDb constructed with an unused DSN is
    therefore safe here: .connection() is never actually called, keeping
    this continuation genuinely hermetic apart from the one real model
    call this function exists to make."""
    substrate = SubstrateApi(
        db=SubstrateDb(dsn="postgresql://unused/unused"),
        run_store=run_store,
        dimensions=settings.models.embedding_dimensions,
        acord_ingestion_enabled=False,
    )
    tools = ToolGateway(run_store=run_store, run_id_for_parse=run_id, substrate_api=substrate)
    return RunContext(
        run_id=run_id,
        substrate=substrate,
        pins=Pins(prompts=dict(_PROMPT_PINS), models={}, tools={}, algorithms={}),
        model_gateway=model_gateway,
        # The run's own real, persisted budget (from the POST /v1/runs
        # request body, or the default create_run() itself seeds) - not
        # a hardcoded constant. GatewayBudget.from_contract() exists
        # specifically to bridge C11Runmanifest.budget into this shape.
        budget=GatewayBudget.from_contract(manifest.budget),
        tools=tools,
    )


def resume_after_checkpoint(
    *,
    run_id: UUID,
    checkpoint: str,
    run_store: RunStore,
    settings: PlatformSettings,
    model_gateway: ModelGateway | None,
) -> C11Runmanifest:
    sealed = run_store.read_sealed_checkpoint(run_id, checkpoint)
    if sealed is None:
        raise CheckpointNotSealedError(f"checkpoint {checkpoint!r} has not been sealed for run {run_id}")
    if not run_store.checkpoint_decisions_complete(run_id, checkpoint):
        raise CheckpointNotCompleteError(f"checkpoint {checkpoint!r} decisions are not yet complete for run {run_id}")

    current_manifest = run_store.read_run_manifest(run_id)
    if current_manifest.corpusHash != sealed["corpusHashAtSeal"]:
        raise CorpusDriftDetected(
            f"run {run_id}'s corpus hash has changed since checkpoint {checkpoint!r} was sealed"
        )

    if model_gateway is None:
        _journal(
            run_store, run_id, stage=checkpoint, outcome="escalated",
            detail="no model provider configured; run cannot continue past this checkpoint automatically",
        )
        return run_store.update_run_state(run_id, "AWAIT_MODEL_PROVIDER")

    if checkpoint != "TRIAGE":
        # RATIFY/ARB accept decisions but have no orchestrator-driven
        # continuation yet - see the module docstring's own scope note.
        return current_manifest

    ctx = _build_run_context(run_id, run_store, settings, model_gateway, current_manifest)

    # Semantic Resolver's own review-band adjudication is deliberately
    # NOT run here - see the module docstring's own discovered-empirically
    # note (SubstrateApi.search() needs a live DB this continuation does
    # not require). Review-band material stays exactly as create_run()
    # sealed it; only S4's own confidently-linked clusters continue.
    all_clusters = list(run_store.read_clusters(run_id))
    review_pairs_pending = len(_rebuild_review_pairs(run_store, run_id))
    _journal(
        run_store, run_id, stage="S5", outcome="ok",
        detail=f"review-band adjudication not run (needs a live DB connection this continuation does not require); {review_pairs_pending} pair(s) remain sealed at TRIAGE",
    )

    # ACORD Aligner's own guardrail G4 means this always degrades in this
    # repo - "not-permitted" is a real, constant fact about this
    # environment (ACORD Reference Architecture data has been unlicensed
    # since Increment 1), not a placeholder value.
    alignments = {
        str(record.clusterId): record
        for record in align_or_degrade(all_clusters, ctx, licence_disposition="not-permitted")
    }

    synthesise = make_canonical_synthesiser_factory(ctx)
    candidates: list[C8Canonicalcandidate] = []
    guardrail_rejections = 0
    for cluster in all_clusters:
        alignment = alignments.get(str(cluster.clusterId))
        member_records = [ctx.substrate.get_attribute(str(run_id), str(m.attributeId)) for m in cluster.members]
        try:
            candidate = synthesise(cluster, alignment, [r.model_dump(mode="json") for r in member_records])
        except GuardrailViolation as exc:
            # A guardrail violation gets zero retries by design (Section
            # 7.6: "retrying a guardrail breach trains nothing and wastes
            # budget") and make_canonical_synthesiser_factory only ever
            # catches WorkItemFailed, not this - one cluster's own naming/
            # tracing violation must not abort synthesis for every other
            # cluster in the run. The concept simply returns to triage,
            # the same "gap" outcome algorithms.coverage.build_universe
            # already gives a cluster with no candidate at all.
            _journal(
                run_store, run_id, stage="S6", outcome="escalated",
                detail=f"{cluster.clusterId}: guardrail violation, no candidate synthesised ({exc})",
            )
            guardrail_rejections += 1
            continue
        if candidate is not None:
            candidates.append(candidate)
    run_store.write_candidates(run_id, candidates)
    _journal(
        run_store, run_id, stage="S6", outcome="ok",
        detail=f"{len(candidates)} candidate(s) synthesised, {guardrail_rejections} guardrail rejection(s)",
    )

    candidates_by_cluster: dict[str, C8Canonicalcandidate] = {}
    for candidate in candidates:
        for ref in candidate.clusterRefs:
            candidates_by_cluster[str(unwrap_ref(ref))] = candidate
    universe = build_universe(all_clusters, candidates_by_cluster, substrate=ctx.substrate, run_id=str(run_id))
    report = coverage(universe, current_manifest.domain, config=settings.coverage)
    gap_register(universe, report, config=settings.coverage)  # computed for real; not persisted here, see module docstring

    _journal(run_store, run_id, stage="S7", outcome="ok", detail=f"coverage score {report.score:.3f}")
    return run_store.update_run_state(run_id, "CANDIDATES_READY")
