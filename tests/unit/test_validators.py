"""Hand-written pass/fail-branch unit tests for contracts/validators.py.

Fixture-file-driven tests (tests/contracts/test_invariants.py) cover the
same invariants against JSON documents; these exercise the Python functions
directly against minimal in-memory generated-model objects, so every branch
(not just what a fixture happens to trigger) is provably covered.
"""

from __future__ import annotations

import hashlib

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry
from generated.C4.CorpusManifest._1_0 import C4Corpusmanifest
from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster
from generated.C8.CanonicalCandidate._1_0 import C8Canonicalcandidate
from generated.C9.CoverageReport._1_0 import C9Coveragereport
from generated.C10.MappingSpec._1_0 import C10Mappingspec

from contracts.validators import (
    _artefact_id_from_evref,
    canonical_json_bytes,
    check_i1_evidence_resolvable,
    check_i2_cluster_members_same_run,
    check_i3_candidate_traces_to_attribute,
    check_i4_coverage_scored_attributes_evidenced,
    check_i5_mapping_entries_have_disposition,
    check_i6_ledger_chain_unbroken,
    ledger_body,
    sign,
)


class TestArtefactIdFromEvref:
    def test_extracts_artefact_id(self) -> None:
        assert _artefact_id_from_evref("evref://us/git/art-1@1234567890abcdef#/x") == "art-1"

    def test_non_evref_scheme_returns_none(self) -> None:
        assert _artefact_id_from_evref("https://example.com/not-an-evref") is None

    def test_malformed_path_shape_returns_none(self) -> None:
        assert _artefact_id_from_evref("evref://us/git") is None

RUN_ID = "11111111-1111-1111-1111-111111111111"


def _sanitisation() -> dict[str, object]:
    return {
        "artefactId": "art-1",
        "contentHash": "b" * 64,
        "labels": ["STRUCTURAL"],
        "verdict": "allow",
        "licenceDisposition": "permitted",
        "policyVersion": 1,
        "classifiedAt": "2026-08-31T12:00:00Z",
    }


def _artefact(artefact_id: str = "art-1") -> C1Sourceartefact:
    return C1Sourceartefact.model_validate({
        "artefactId": artefact_id,
        "region": "us",
        "system": "git",
        "uri": "https://example.com/repo",
        "version": "abc123",
        "contentHash": "b" * 64,
        "evidenceTier": 1,
        "sanitisation": {**_sanitisation(), "artefactId": artefact_id},
    })


def _manifest(artefact_ids: list[str]) -> C4Corpusmanifest:
    return C4Corpusmanifest.model_validate({
        "runId": RUN_ID,
        "domain": "claims",
        "sealedAt": "2026-08-31T12:00:00Z",
        "corpusHash": "a" * 64,
        "artefacts": [_artefact(aid).model_dump(mode="json") for aid in artefact_ids],
        "exclusions": [],
    })


def _attribute(attribute_id: str, evref_artefact_id: str, run_id: str = RUN_ID) -> C5Attributerecord:
    return C5Attributerecord.model_validate({
        "attributeId": attribute_id,
        "runId": run_id,
        "region": "us",
        "sourceContract": evref_artefact_id,
        "path": "claim.claimDate",
        "localName": "claimDate",
        "dataType": "date",
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://us/git/{evref_artefact_id}@1234567890abcdef#/x"],
    })


class TestI1EvidenceResolvable:
    def test_resolvable_evidence_passes(self) -> None:
        manifest = _manifest(["art-1"])
        attr = _attribute("attr://us/claims-v1/x", "art-1")
        assert check_i1_evidence_resolvable([attr], manifest) == []

    def test_unresolvable_evidence_fails(self) -> None:
        manifest = _manifest(["art-1"])
        attr = _attribute("attr://us/claims-v1/x", "art-missing")
        violations = check_i1_evidence_resolvable([attr], manifest)
        assert len(violations) == 1
        assert violations[0].invariant == "I1"


class TestI2ClusterMembersSameRun:
    def _cluster(self, attribute_id: str) -> C6Conceptcluster:
        return C6Conceptcluster.model_validate({
            "clusterId": "cluster://x",
            "proposedConcept": "claimDate",
            "members": [{"attributeId": attribute_id, "region": "us", "role": "core", "pairScore": 1.0}],
            "confidence": 0.9,
            "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
        })

    def test_member_in_same_run_passes(self) -> None:
        attr = _attribute("attr://us/claims-v1/x", "art-1", run_id=RUN_ID)
        cluster = self._cluster("attr://us/claims-v1/x")
        assert check_i2_cluster_members_same_run([cluster], [attr], RUN_ID) == []

    def test_member_missing_attribute_fails(self) -> None:
        cluster = self._cluster("attr://us/claims-v1/missing")
        violations = check_i2_cluster_members_same_run([cluster], [], RUN_ID)
        assert len(violations) == 1 and violations[0].invariant == "I2"

    def test_member_from_different_run_fails(self) -> None:
        other_run = "22222222-2222-2222-2222-222222222222"
        attr = _attribute("attr://us/claims-v1/x", "art-1", run_id=other_run)
        cluster = self._cluster("attr://us/claims-v1/x")
        violations = check_i2_cluster_members_same_run([cluster], [attr], RUN_ID)
        assert len(violations) == 1 and violations[0].invariant == "I2"


class TestI3CandidateTracesToAttribute:
    def _candidate(self, cluster_refs: list[str]) -> C8Canonicalcandidate:
        return C8Canonicalcandidate.model_validate({
            "candidateId": "canon://Claim.claimDate",
            "entity": "Claim",
            "attribute": "claimDate",
            "dataType": "date",
            "cardinality": "1..1",
            "obligation": {"level": "mandatory"},
            "placement": "core",
            "placementRule": "3 regions present",
            "namingSource": "derived",
            "rationale": "r",
            "clusterRefs": cluster_refs,
            "weight": 5,
            "ratification": {"status": "pending", "sme": None, "decidedAt": None},
        })

    def _cluster(self, attribute_id: str) -> C6Conceptcluster:
        return C6Conceptcluster.model_validate({
            "clusterId": "cluster://x",
            "proposedConcept": "claimDate",
            "members": [{"attributeId": attribute_id, "region": "us", "role": "core", "pairScore": 1.0}],
            "confidence": 0.9,
            "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
        })

    def test_candidate_tracing_to_real_attribute_passes(self) -> None:
        attr = _attribute("attr://us/claims-v1/x", "art-1")
        cluster = self._cluster("attr://us/claims-v1/x")
        candidate = self._candidate(["cluster://x"])
        assert check_i3_candidate_traces_to_attribute([candidate], [cluster], [attr]) == []

    def test_candidate_with_unresolvable_cluster_ref_fails(self) -> None:
        candidate = self._candidate(["cluster://does-not-exist"])
        violations = check_i3_candidate_traces_to_attribute([candidate], [], [])
        assert len(violations) == 1 and violations[0].invariant == "I3"

    def test_candidate_whose_cluster_has_no_real_attribute_fails(self) -> None:
        cluster = self._cluster("attr://us/claims-v1/orphan")
        candidate = self._candidate(["cluster://x"])
        violations = check_i3_candidate_traces_to_attribute([candidate], [cluster], [])
        assert len(violations) == 1 and violations[0].invariant == "I3"

    def test_candidate_with_no_cluster_refs_fails(self) -> None:
        # C8's clusterRefs carries minItems=1, so this shape can't be built
        # via C8Canonicalcandidate.model_validate() - the check's own guard
        # is defence-in-depth, tested directly via a stand-in the same way
        # as TestI5's "neither" case below.
        from types import SimpleNamespace

        candidate = SimpleNamespace(candidateId="canon://x", clusterRefs=[])
        violations = check_i3_candidate_traces_to_attribute([candidate], [], [])  # type: ignore[list-item]
        assert len(violations) == 1 and violations[0].invariant == "I3"


class TestI4CoverageScoredAttributesEvidenced:
    def _report(self) -> C9Coveragereport:
        return C9Coveragereport.model_validate({
            "domain": "claims",
            "score": 0.9,
            "denominator": 10,
            "weightSum": 30,
            "perRegion": {"us": 0.9, "uk": 0.9, "eu": 0.9},
            "gate1Pass": True,
            "gate2Pass": True,
            "gate3Pass": True,
            "specifiedVsInferred": {"specified": 8, "inferred": 2},
            "exclusions": [],
        })

    def test_evidenced_and_smed_attribute_passes(self) -> None:
        report = self._report()
        scored: list[dict[str, object]] = [{"conceptId": "cluster://x", "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"], "ratifyingSme": "alice"}]
        assert check_i4_coverage_scored_attributes_evidenced(report, scored) == []

    def test_missing_sme_fails(self) -> None:
        report = self._report()
        scored: list[dict[str, object]] = [{"conceptId": "cluster://x", "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"], "ratifyingSme": None}]
        violations = check_i4_coverage_scored_attributes_evidenced(report, scored)
        assert len(violations) == 1 and violations[0].invariant == "I4"

    def test_missing_evidence_fails(self) -> None:
        report = self._report()
        scored: list[dict[str, object]] = [{"conceptId": "cluster://x", "evidenceRefs": [], "ratifyingSme": "alice"}]
        violations = check_i4_coverage_scored_attributes_evidenced(report, scored)
        assert len(violations) == 1 and violations[0].invariant == "I4"


class TestI5MappingEntriesHaveDisposition:
    def _header(self) -> dict[str, object]:
        return {
            "mappingSpecId": "m1",
            "canonicalRef": "canon://Claim.claimDate",
            "direction": "toCanonical",
            "generatedFrom": {"run": RUN_ID, "corpusManifest": "c", "agent": "a"},
        }

    def test_transform_only_passes(self) -> None:
        spec = C10Mappingspec.model_validate({
            "header": self._header(),
            "mappings": [{"canonical": "x", "evidence": ["evref://us/git/art-1@1234567890abcdef#/x"], "transform": "identity()"}],
        })
        assert check_i5_mapping_entries_have_disposition(spec) == []

    def test_disposition_only_passes(self) -> None:
        spec = C10Mappingspec.model_validate({
            "header": self._header(),
            "mappings": [{"canonical": "x", "evidence": ["evref://us/git/art-1@1234567890abcdef#/x"], "disposition": {"status": "unmapped", "reason": "no equivalent field"}}],
        })
        assert check_i5_mapping_entries_have_disposition(spec) == []

    def test_both_transform_and_disposition_fails(self) -> None:
        spec = C10Mappingspec.model_validate({
            "header": self._header(),
            "mappings": [{"canonical": "x", "evidence": ["evref://us/git/art-1@1234567890abcdef#/x"], "transform": "identity()", "disposition": {"status": "unmapped", "reason": "r"}}],
        })
        violations = check_i5_mapping_entries_have_disposition(spec)
        assert len(violations) == 1 and violations[0].invariant == "I5"

    def test_neither_transform_nor_disposition_fails(self) -> None:
        # This shape is actually rejected by C10Mappingspec.model_validate()
        # itself (neither generated union variant, Mappings or Mappings1,
        # matches when both required fields are absent) - so the "neither"
        # branch can't be reached via normal validation. It's still tested
        # directly, via a lightweight stand-in with the same attribute
        # surface check_i5 reads, as defence-in-depth documentation of the
        # intended behaviour if that structural guarantee ever changes.
        from types import SimpleNamespace

        spec = SimpleNamespace(
            header=SimpleNamespace(mappingSpecId="m1"),
            mappings=[SimpleNamespace(transform=None, disposition=None)],
        )
        violations = check_i5_mapping_entries_have_disposition(spec)  # type: ignore[arg-type]
        assert len(violations) == 1 and violations[0].invariant == "I5"

    def test_disposition_without_reason_fails(self) -> None:
        # C10's Disposition object carries reason as required, so this
        # shape can't be built via C10Mappingspec.model_validate() either -
        # same defence-in-depth pattern as the "neither" case above.
        from types import SimpleNamespace

        spec = SimpleNamespace(
            header=SimpleNamespace(mappingSpecId="m1"),
            mappings=[SimpleNamespace(transform=None, disposition=SimpleNamespace(reason=""))],
        )
        violations = check_i5_mapping_entries_have_disposition(spec)  # type: ignore[arg-type]
        assert len(violations) == 1 and violations[0].invariant == "I5"


class TestI6LedgerChainUnbroken:
    def _entry(self, entry_id: str, prev_hash: str | None) -> C3Egressledgerentry:
        """Builds an entry whose `hash` is genuinely
        sha256(canonical_json_bytes(ledger_body(entry))) - the same
        recipe check_i6_ledger_chain_unbroken now recomputes - rather
        than an arbitrary placeholder string, so these tests exercise
        real integrity verification, not merely prevHash linkage."""
        entry = C3Egressledgerentry.model_validate({
            "entryId": entry_id,
            "at": "2026-08-31T12:00:00Z",
            "region": "us",
            "artefactId": "art-1",
            "contentHash": "b" * 64,
            "classification": ["STRUCTURAL"],
            "verdict": "allow",
            "policyVersion": 1,
            "lawfulBasis": "legitimate-interest",
            "approver": None,
            "runId": RUN_ID,
            "prevHash": prev_hash,
            "hash": "0" * 64,
            "signature": "sig",
        })
        real_hash = hashlib.sha256(canonical_json_bytes(ledger_body(entry))).hexdigest()
        return entry.model_copy(update={"hash": real_hash})

    def test_unbroken_chain_passes(self) -> None:
        e1 = self._entry("e1", None)
        e2 = self._entry("e2", str(e1.hash))
        assert check_i6_ledger_chain_unbroken([e1, e2]) == []

    def test_genesis_with_non_null_prev_hash_fails(self) -> None:
        e1 = self._entry("e1", "f" * 64)
        violations = check_i6_ledger_chain_unbroken([e1])
        assert len(violations) == 1 and violations[0].invariant == "I6"

    def test_broken_chain_fails(self) -> None:
        e1 = self._entry("e1", None)
        e2 = self._entry("e2", "c" * 64)
        violations = check_i6_ledger_chain_unbroken([e1, e2])
        assert len(violations) == 1 and violations[0].invariant == "I6"

    def test_mixed_regions_rejected(self) -> None:
        e1 = self._entry("e1", None)
        e2 = C3Egressledgerentry.model_validate({**e1.model_dump(mode="json"), "entryId": "e2", "region": "uk", "prevHash": str(e1.hash)})
        violations = check_i6_ledger_chain_unbroken([e1, e2])
        assert len(violations) == 1 and violations[0].invariant == "I6"

    def test_tampered_hash_detected(self) -> None:
        e1 = self._entry("e1", None)
        tampered = e1.model_copy(update={"hash": "f" * 64})
        violations = check_i6_ledger_chain_unbroken([tampered])
        assert any(v.invariant == "I6" and "tampered" in v.detail for v in violations)

    def test_signature_verified_when_signing_key_supplied(self) -> None:
        key = bytes.fromhex("a" * 64)
        e1 = self._entry("e1", None)
        signed = e1.model_copy(update={"signature": sign(key, str(e1.hash))})
        assert check_i6_ledger_chain_unbroken([signed], signing_key=key) == []

    def test_signature_rejected_with_wrong_key(self) -> None:
        key_a = bytes.fromhex("a" * 64)
        key_b = bytes.fromhex("b" * 64)
        e1 = self._entry("e1", None)
        signed = e1.model_copy(update={"signature": sign(key_a, str(e1.hash))})
        violations = check_i6_ledger_chain_unbroken([signed], signing_key=key_b)
        assert any("signature" in v.detail for v in violations)

    def test_empty_list_passes(self) -> None:
        assert check_i6_ledger_chain_unbroken([]) == []
