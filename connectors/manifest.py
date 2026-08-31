"""
CorpusManifest assembly (Section 3.4 + Section 8.1).

S1 "Corpus assembly" is a barrier stage; its exit criterion is "Manifest
sealed; every candidate source included with a version or excluded with a
reason." This module is the discover -> filter -> fetch -> gate -> seal
pipeline that produces that sealed manifest. Increment 4 replaces the
Increment 2 placeholder sanitisation (an unconditional verdict=allow) with
the real gate (gate.gate.classify_and_redact): every kept ArtefactRef is
now genuinely classified, masked where needed, policy-evaluated, and
ledgered - a deliberate breaking signature change, since a real gate
cannot run without real config/policy/ledger access.

corpusHash construction is a builder decision: the schema only says "sha256
over the sorted artefact content hashes," without specifying encoding. This
reuses the one precedent the spec gives elsewhere for a similar problem -
the egress ledger's canonical_json convention (Section 5.3): "sorted keys
and no insignificant whitespace so that hashes are reproducible." Mask-
then-hash: an artefact's contentHash is now the hash of its GATED
(possibly redacted) content, not the raw fetched bytes - matching the
content-addressed evidence-store model, where the bytes at a given hash
must be exactly what a downstream reader would actually retrieve.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C2.SanitisationRecord._1_0 import LicenceDisposition
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.common.defs import ExclusionEntry, Region, System

from config.settings import EgressConfig, FeatureFlags, RelevanceConfig
from connectors.base import ArtefactRef, Connector, ConnectorScope
from connectors.relevance import filter_relevance
from gate.evidence_store import EvidenceStore
from gate.gate import classify_and_redact
from gate.ledger import LedgerStore
from gate.policy import PolicyDocument
from gate.tokenisation import region_key_bytes

_DEFAULT_EVIDENCE_TIER_BY_SYSTEM: Mapping[str, int] = {
    "git": 1, "ado": 1, "bitbucket": 1, "gitlab": 1,     # deployed/versioned contract source
    "confluence": 3, "jira": 3,                            # documentary evidence
    "catalogue": 2, "vendor": 4,
}
"""git=1 / confluence=3 mirrors the values already used in
tests/fixtures/contracts/C4/CorpusManifest/positive/claims_us_uk.json
(Increment 1) for continuity. Not a policy knob the spec names; a builder
default."""

_DEFAULT_LICENCE_DISPOSITION_BY_SYSTEM: Mapping[str, LicenceDisposition] = {
    "git": LicenceDisposition.permitted,
    "ado": LicenceDisposition.permitted,
    "bitbucket": LicenceDisposition.permitted,
    "gitlab": LicenceDisposition.permitted,
    "confluence": LicenceDisposition.permitted,
    "jira": LicenceDisposition.permitted,
    "catalogue": LicenceDisposition.permitted,
    "vendor": LicenceDisposition.unknown,
}
"""Internal source systems (git/ado/.../catalogue) default to permitted -
they're the syndicate's own estate. vendor defaults to unknown (Section
5.4's block-unlicensed rule treats unknown the same as prohibited) since
third-party vendor material's licence position isn't established just by
virtue of having been fetched. Not a policy knob the spec names; a
builder default, same status as _DEFAULT_EVIDENCE_TIER_BY_SYSTEM."""


def canonical_json_bytes(value: object) -> bytes:
    """Sorted keys, no insignificant whitespace - the same recipe the
    spec's egress ledger canonical_json uses, reused here since the C4
    schema doesn't specify corpusHash's exact byte encoding."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_corpus_hash(content_hashes: Sequence[str]) -> str:
    """sha256 over the canonical-JSON-encoded, SORTED list of artefact
    contentHash strings. Sorting first is what makes the result
    order-independent - and therefore stable across repeats regardless of
    connector iteration order - which is the literal property Increment
    2's acceptance test checks."""
    return hashlib.sha256(canonical_json_bytes(sorted(content_hashes))).hexdigest()


def _artefact_id_for(ref: ArtefactRef) -> str:
    """Deterministic, not a random UUID - matches this repo's identity
    philosophy (docs/contracts.md: "never a random UUID"). A slug of
    system/region/uri so the same source gets the same artefactId across
    independent runs, which is what lets corpusHash be compared for
    equality across repeats in the first place."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ref.uri).strip("-").lower()
    return f"{ref.system}-{ref.region}-{slug}"[:200]


class _LedgerSequencer:
    """Tracks, per region, the next ledger entry id and the running
    prevHash chain WITHIN one assemble_corpus_manifest call - a single
    run typically appends several entries per region in sequence, and
    each one must chain onto the one before it, including entries
    appended earlier in this same run (not just what ledger_store already
    had on disk before the run started)."""

    def __init__(self, ledger_store: LedgerStore) -> None:
        self._ledger_store = ledger_store
        self._seq_by_region: dict[str, int] = {}
        self._latest_hash_by_region: dict[str, str | None] = {}

    def next_entry_id(self, region: str) -> str:
        if region not in self._seq_by_region:
            self._seq_by_region[region] = len(self._ledger_store.read_all(region))
        self._seq_by_region[region] += 1
        return f"ledger-{region}-{self._seq_by_region[region]:06d}"

    def prev_hash(self, region: str) -> str | None:
        if region not in self._latest_hash_by_region:
            self._latest_hash_by_region[region] = self._ledger_store.latest_hash(region)
        return self._latest_hash_by_region[region]

    def record(self, region: str, new_hash: str) -> None:
        self._latest_hash_by_region[region] = new_hash


def assemble_corpus_manifest(
    run_id: UUID,
    domain: str,
    sources: Sequence[tuple[Connector, ConnectorScope]],
    cfg: RelevanceConfig,
    egress_cfg: EgressConfig,
    policy: PolicyDocument,
    feature_flags: FeatureFlags,
    ledger_store: LedgerStore,
    evidence_store: EvidenceStore,
    evidence_tier_by_system: Mapping[str, int] = _DEFAULT_EVIDENCE_TIER_BY_SYSTEM,
    licence_disposition_by_system: Mapping[str, LicenceDisposition] = _DEFAULT_LICENCE_DISPOSITION_BY_SYSTEM,
    sealed_at: datetime | None = None,
) -> C4Corpusmanifest:
    """discover (every source) -> filter_relevance (pass 1, then the
    uncertain-band default policy) -> fetch only what's kept -> gate
    (classify, mask, policy-evaluate, ledger) each kept artefact -> seal
    into a schema-valid C4Corpusmanifest. A gate-blocked artefact is
    recorded in .exclusions (reason licence-blocked or policy-blocked),
    not .artefacts - it is never fetched-and-forgotten (Section 5.6: "What
    MUST NOT happen is that the run proceeds as though the artefact never
    existed").

    sealedAt/runId legitimately differ between two independent invocations
    (a real timestamp, a fresh UUID per run) - only corpusHash is required
    to be stable, and is, by construction (compute_corpus_hash sorts
    first). A whole-document diff across repeats is therefore expected,
    not a bug.
    """
    all_refs: list[ArtefactRef] = []
    for connector, scope in sources:
        all_refs.extend(connector.discover(scope))

    keep, exclusions = filter_relevance(all_refs, domain, cfg)

    connectors_by_system = {connector.system: connector for connector, _ in sources}
    classified_at = sealed_at or datetime.now(timezone.utc)
    sequencer = _LedgerSequencer(ledger_store)

    artefacts: list[C1Sourceartefact] = []
    for ref in keep:
        raw = connectors_by_system[ref.system].fetch(ref)
        artefact_id = _artefact_id_for(ref)
        licence_disposition = licence_disposition_by_system.get(ref.system, LicenceDisposition.unknown)
        region_key = region_key_bytes(ref.region, egress_cfg)

        result = classify_and_redact(
            content=raw.content,
            media_type=raw.media_type,
            entry_id=sequencer.next_entry_id(ref.region),
            artefact_id=artefact_id,
            region=ref.region,
            run_id=run_id,
            licence_disposition=licence_disposition,
            classified_at=classified_at,
            policy=policy,
            policy_version=egress_cfg.policy_version,
            lawful_basis=egress_cfg.lawful_basis,
            region_key=region_key,
            signing_key=bytes.fromhex(egress_cfg.ledger_signing_key),
            prev_ledger_hash=sequencer.prev_hash(ref.region),
            override_enabled=feature_flags.gate_dpo_override_enabled,
        )
        ledger_store.append(result.ledger_entry)
        sequencer.record(ref.region, str(result.ledger_entry.hash))

        if result.admitted:
            evidence_store.write_artefact(result.content_hash, result.redacted_content)
            assert result.sanitisation_record is not None
            artefacts.append(C1Sourceartefact(
                artefactId=artefact_id,
                region=Region(ref.region),
                system=System(ref.system),
                uri=ref.uri,
                version=raw.version,
                contentHash=result.content_hash,
                mediaType=raw.media_type,
                owningTeam=raw.owning_team,
                evidenceTier=evidence_tier_by_system[ref.system],
                sanitisation=result.sanitisation_record,
            ))
        else:
            assert result.exclusion_reason is not None
            exclusions.append(ExclusionEntry(
                uri=ref.uri,
                reason=result.exclusion_reason,
                detail=result.policy_reason,
                decidedBy="gate",
            ))

    return C4Corpusmanifest(
        runId=run_id,
        domain=domain,
        sealedAt=classified_at,
        corpusHash=compute_corpus_hash([artefact.contentHash for artefact in artefacts]),
        artefacts=artefacts,
        exclusions=exclusions,
    )
