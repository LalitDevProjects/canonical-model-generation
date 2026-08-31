"""
Increment 4's literal acceptance test (Section 17.2): "The planted
personal-data example is masked; the licence-restricted artefact is
blocked and appears in exclusions; the ledger chain verifies."

The third clause (the ledger chain verifies) is exercised end-to-end in
tests/gate/test_ledger.py (a real round trip through LedgerStore, plus a
deliberately corrupted entry proving check_i6 actually catches tampering
rather than merely passing a clean chain) - not repeated here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from generated.C2.SanitisationRecord._1_0 import LicenceDisposition
from generated.common.defs import SanitisationLabel

from config.settings import load_settings
from connectors.base import ArtefactRef, Connector, ConnectorScope, HealthStatus, RawArtefact
from connectors.manifest import assemble_corpus_manifest
from gate.evidence_store import EvidenceStore
from gate.gate import classify_and_redact
from gate.ledger import LedgerStore
from gate.policy import load_policy_document

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_GATE_FIXTURE = REPO_ROOT / "golden" / "gate" / "uk" / "claim-with-example.yaml"
GOLDEN_UK_OPENAPI = REPO_ROOT / "golden" / "git" / "claims-uk" / "openapi.yaml"
AT = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


class _RealFileConnector(Connector):
    """Fetches real golden/ content from disk, without needing a real git
    repository - GitConnector itself (real `git ls-tree`/`git show`
    plumbing) is independently proven in test_git_connector.py; this
    acceptance test's own job is the gate's block-and-exclude behaviour
    against real golden corpus bytes, not re-proving connector mechanics."""

    system = "git"

    def __init__(self, region: str, path: Path) -> None:
        self._region = region
        self._path = path

    def discover(self, scope: ConnectorScope) -> Iterator[ArtefactRef]:
        yield ArtefactRef(
            uri=f"git://golden/{self._path.relative_to(REPO_ROOT).as_posix()}",
            system=self.system,
            region=self._region,
            media_type="application/yaml",
            title=self._path.name,
        )

    def fetch(self, ref: ArtefactRef) -> RawArtefact:
        return RawArtefact(
            uri=ref.uri, version="v1", content=self._path.read_bytes(),
            media_type=ref.media_type, owning_team=None, metadata={},
        )

    def health(self) -> HealthStatus:
        return HealthStatus(system=self.system, ok=True)


class TestPlantedPersonalDataExampleIsMasked:
    """Runs classify_and_redact directly against the real, checked-in
    golden fixture content (not a synthetic string) - the same fixture
    Increment 5+ connectors will fetch from golden/gate/uk/ via
    GitConnector, same as every other golden/ bucket."""

    def test_masked_with_expected_labels_and_tokenised_output(self) -> None:
        content = GOLDEN_GATE_FIXTURE.read_bytes()
        settings = load_settings()
        policy = load_policy_document(expected_version=settings.egress.policy_version)
        region_key = bytes.fromhex(settings.egress.tokenisation_keys["uk"])
        signing_key = bytes.fromhex(settings.egress.ledger_signing_key)

        result = classify_and_redact(
            content=content,
            media_type="application/yaml",
            entry_id="ledger-uk-000001",
            artefact_id="art-claims-uk-gate-fixture",
            region="uk",
            run_id=uuid4(),
            licence_disposition=LicenceDisposition.permitted,
            classified_at=AT,
            policy=policy,
            policy_version=settings.egress.policy_version,
            lawful_basis=settings.egress.lawful_basis,
            region_key=region_key,
            signing_key=signing_key,
            prev_ledger_hash=None,
        )

        assert result.admitted is True
        assert result.sanitisation_record is not None
        assert result.sanitisation_record.verdict == "mask"
        assert SanitisationLabel.SAMPLE_VALUE in result.sanitisation_record.labels
        assert SanitisationLabel.IDENTIFYING in result.sanitisation_record.labels
        assert result.ledger_entry.verdict == "mask"

        # The raw planted values are gone from what would be stored...
        assert b"A. Smith, SW1A 1AA" not in result.redacted_content
        assert b"SW1A 1AA" not in result.redacted_content
        # ...replaced by a deterministic, label-prefixed token.
        assert b"<SAMPLE_VALUE:" in result.redacted_content


class TestLicenceRestrictedArtefactIsBlockedAndExcluded:
    """End-to-end through assemble_corpus_manifest, not classify_and_redact
    directly - "appears in exclusions" is a CorpusManifest-level claim."""

    def test_blocked_and_recorded_in_exclusions(self, tmp_path: Path) -> None:
        settings = load_settings()
        git_connector = _RealFileConnector(region="uk", path=GOLDEN_UK_OPENAPI)
        scope = ConnectorScope(region="uk", domain="claims")
        ledger_store = LedgerStore(base_path=tmp_path / "ledger")
        evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")

        manifest = assemble_corpus_manifest(
            run_id=uuid4(),
            domain="claims",
            sources=[(git_connector, scope)],
            cfg=settings.relevance,
            egress_cfg=settings.egress,
            policy=load_policy_document(expected_version=settings.egress.policy_version),
            feature_flags=settings.feature_flags,
            ledger_store=ledger_store,
            evidence_store=evidence_store,
            # git defaults to a permitted licence disposition (see
            # connectors/manifest.py's _DEFAULT_LICENCE_DISPOSITION_BY_SYSTEM) -
            # overridden here to plant the licence-restricted case, the
            # same pattern evidence_tier_by_system already uses.
            licence_disposition_by_system={"git": LicenceDisposition.prohibited},
        )

        assert manifest.artefacts == []
        assert len(manifest.exclusions) == 1
        exclusion = manifest.exclusions[0]
        assert exclusion.reason == "licence-blocked"
        assert exclusion.decidedBy == "gate"

    def test_the_ref_still_reaches_the_ledger_as_a_block_verdict(self, tmp_path: Path) -> None:
        settings = load_settings()
        git_connector = _RealFileConnector(region="uk", path=GOLDEN_UK_OPENAPI)
        scope = ConnectorScope(region="uk", domain="claims")
        ledger_store = LedgerStore(base_path=tmp_path / "ledger")
        evidence_store = EvidenceStore(base_path=tmp_path / "evidence-store")

        assemble_corpus_manifest(
            run_id=uuid4(),
            domain="claims",
            sources=[(git_connector, scope)],
            cfg=settings.relevance,
            egress_cfg=settings.egress,
            policy=load_policy_document(expected_version=settings.egress.policy_version),
            feature_flags=settings.feature_flags,
            ledger_store=ledger_store,
            evidence_store=evidence_store,
            licence_disposition_by_system={"git": LicenceDisposition.prohibited},
        )

        entries = ledger_store.read_all("uk")
        assert len(entries) == 1
        assert entries[0].verdict == "block"
