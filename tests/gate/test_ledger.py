from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from generated.C3.EgressLedgerEntry._1_0 import C3Egressledgerentry

from contracts.validators import check_i6_ledger_chain_unbroken
from gate.ledger import LedgerStore, append_ledger_entry

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
SIGNING_KEY = bytes.fromhex("a" * 64)
AT = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def _entry(entry_id: str, prev_hash: str | None) -> C3Egressledgerentry:
    return append_ledger_entry(
        entry_id=entry_id,
        at=AT,
        region="us",
        artefact_id="art-1",
        content_hash="b" * 64,
        labels=["STRUCTURAL"],
        verdict="allow",
        policy_version=3,
        lawful_basis="legitimate-interest",
        approver=None,
        run_id=RUN_ID,
        prev_hash=prev_hash,
        signing_key=SIGNING_KEY,
    )


class TestAppendLedgerEntry:
    def test_produces_a_schema_valid_entry_with_a_real_hash_and_signature(self) -> None:
        entry = _entry("e1", None)
        assert len(str(entry.hash)) == 64
        assert entry.signature

    def test_deterministic_for_the_same_inputs(self) -> None:
        assert _entry("e1", None).hash == _entry("e1", None).hash

    def test_check_i6_accepts_a_freshly_produced_chain(self) -> None:
        e1 = _entry("e1", None)
        e2 = _entry("e2", str(e1.hash))
        assert check_i6_ledger_chain_unbroken([e1, e2], signing_key=SIGNING_KEY) == []

    def test_check_i6_rejects_a_signature_from_the_wrong_key(self) -> None:
        e1 = _entry("e1", None)
        wrong_key = bytes.fromhex("b" * 64)
        violations = check_i6_ledger_chain_unbroken([e1], signing_key=wrong_key)
        assert any("signature" in v.detail for v in violations)


class TestLedgerStore:
    def test_append_then_read_all_round_trips(self, tmp_path: Path) -> None:
        store = LedgerStore(base_path=tmp_path)
        e1 = _entry("e1", None)
        e2 = _entry("e2", str(e1.hash))
        store.append(e1)
        store.append(e2)
        read_back = store.read_all("us")
        assert [e.entryId for e in read_back] == ["e1", "e2"]

    def test_read_all_on_a_region_with_no_entries_returns_empty(self, tmp_path: Path) -> None:
        store = LedgerStore(base_path=tmp_path)
        assert store.read_all("us") == []

    def test_latest_hash_tracks_the_most_recently_appended_entry(self, tmp_path: Path) -> None:
        store = LedgerStore(base_path=tmp_path)
        assert store.latest_hash("us") is None
        e1 = _entry("e1", None)
        store.append(e1)
        assert store.latest_hash("us") == str(e1.hash)

    def test_append_is_additive_not_overwriting(self, tmp_path: Path) -> None:
        store = LedgerStore(base_path=tmp_path)
        store.append(_entry("e1", None))
        store.append(_entry("e2", str(store.latest_hash("us"))))
        path = tmp_path / "us" / "entries.jsonl"
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_a_freshly_read_back_chain_still_verifies_via_check_i6(self, tmp_path: Path) -> None:
        store = LedgerStore(base_path=tmp_path)
        e1 = _entry("e1", None)
        e2 = _entry("e2", str(e1.hash))
        store.append(e1)
        store.append(e2)
        read_back = store.read_all("us")
        assert check_i6_ledger_chain_unbroken(read_back, signing_key=SIGNING_KEY) == []

    def test_check_i6_detects_a_corrupted_entry_after_a_round_trip(self, tmp_path: Path) -> None:
        # Same break-then-fix discipline as I1's CI regen-and-diff gate:
        # prove the extended check_i6 actually catches tampering, not
        # just that a clean chain passes.
        store = LedgerStore(base_path=tmp_path)
        e1 = _entry("e1", None)
        store.append(e1)
        read_back = store.read_all("us")
        tampered = read_back[0].model_copy(update={"contentHash": "f" * 64})
        violations = check_i6_ledger_chain_unbroken([tampered], signing_key=SIGNING_KEY)
        assert any("tampered" in v.detail for v in violations)
