"""
CorpusManifest assembly (Section 3.4 + Section 8.1).

S1 "Corpus assembly" is a barrier stage; its exit criterion is "Manifest
sealed; every candidate source included with a version or excluded with a
reason." This module is the discover -> filter -> fetch -> hash -> seal
pipeline that produces that sealed manifest.

corpusHash construction is a builder decision: the schema only says "sha256
over the sorted artefact content hashes," without specifying encoding. This
reuses the one precedent the spec gives elsewhere for a similar problem -
the egress ledger's canonical_json convention (Section 5.3): "sorted keys
and no insignificant whitespace so that hashes are reproducible."
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C2.SanitisationRecord._1_0 import C2Sanitisationrecord, LicenceDisposition
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.common.defs import Region, SanitisationLabel, SanitisationVerdict, System

from config.settings import RelevanceConfig
from connectors.base import ArtefactRef, Connector, ConnectorScope
from connectors.relevance import filter_relevance

_DEFAULT_EVIDENCE_TIER_BY_SYSTEM: Mapping[str, int] = {
    "git": 1, "ado": 1, "bitbucket": 1, "gitlab": 1,     # deployed/versioned contract source
    "confluence": 3, "jira": 3,                            # documentary evidence
    "catalogue": 2, "vendor": 4,
}
"""git=1 / confluence=3 mirrors the values already used in
tests/fixtures/contracts/C4/CorpusManifest/positive/claims_us_uk.json
(Increment 1) for continuity. Not a policy knob the spec names; a builder
default."""

_PLACEHOLDER_POLICY_VERSION = 1
_PLACEHOLDER_CLASSIFIED_BY = "increment2-placeholder-gate"


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


def _placeholder_sanitisation(
    artefact_id: str, content_hash: str, classified_at: datetime
) -> C2Sanitisationrecord:
    """Interim stand-in for the real sanitisation gate (Increment 4).
    Every FETCHED artefact gets an honestly-labelled placeholder verdict -
    classifiedBy is tagged so it's unambiguous this isn't a real gate
    decision. Excluded refs never reach this function at all: relevance
    filtering runs on ArtefactRefs from discover(), before fetch(), so an
    excluded ref is never fetched and never needs a SanitisationRecord."""
    return C2Sanitisationrecord(
        artefactId=artefact_id,
        contentHash=content_hash,
        labels=[SanitisationLabel.STRUCTURAL],
        verdict=SanitisationVerdict.allow,
        licenceDisposition=LicenceDisposition.permitted,
        policyVersion=_PLACEHOLDER_POLICY_VERSION,
        classifiedAt=classified_at,
        classifiedBy=_PLACEHOLDER_CLASSIFIED_BY,
    )


def assemble_corpus_manifest(
    run_id: UUID,
    domain: str,
    sources: Sequence[tuple[Connector, ConnectorScope]],
    cfg: RelevanceConfig,
    evidence_tier_by_system: Mapping[str, int] = _DEFAULT_EVIDENCE_TIER_BY_SYSTEM,
    sealed_at: datetime | None = None,
) -> C4Corpusmanifest:
    """discover (every source) -> filter_relevance (pass 1, then the
    uncertain-band default policy) -> fetch only what's kept -> hash each
    artefact's content -> seal into a schema-valid C4Corpusmanifest.

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

    artefacts: list[C1Sourceartefact] = []
    for ref in keep:
        raw = connectors_by_system[ref.system].fetch(ref)
        content_hash = hashlib.sha256(raw.content).hexdigest()
        artefact_id = _artefact_id_for(ref)
        artefacts.append(C1Sourceartefact(
            artefactId=artefact_id,
            region=Region(ref.region),
            system=System(ref.system),
            uri=ref.uri,
            version=raw.version,
            contentHash=content_hash,
            mediaType=raw.media_type,
            owningTeam=raw.owning_team,
            evidenceTier=evidence_tier_by_system[ref.system],
            sanitisation=_placeholder_sanitisation(artefact_id, content_hash, classified_at),
        ))

    return C4Corpusmanifest(
        runId=run_id,
        domain=domain,
        sealedAt=classified_at,
        corpusHash=compute_corpus_hash([artefact.contentHash for artefact in artefacts]),
        artefacts=artefacts,
        exclusions=exclusions,
    )
