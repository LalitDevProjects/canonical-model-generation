from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from pipeline.run_store import RunStore
from tools.gateway import ToolDenied, ToolGateway


def _gateway(tmp_path: Path) -> ToolGateway:
    return ToolGateway(run_store=RunStore(base_path=tmp_path), run_id_for_parse=uuid4())


class TestAuthorisation:
    def test_authorised_agent_can_call_its_own_tool(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        result = gateway.call("schema-interpreter", "artefact.write", {"kind": "x", "payload": {}}, run_id)
        assert isinstance(result, dict)
        assert "artefactRef" in result

    def test_unauthorised_agent_is_denied(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(ToolDenied):
            gateway.call("repository-scout", "acord.lookup", {"query": "x"}, run_id)

    def test_unknown_tool_is_denied(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(ToolDenied):
            gateway.call("schema-interpreter", "not.a.real.tool", {}, run_id)


class TestArgumentSchemaValidation:
    def test_missing_required_argument_raises(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(Exception):  # jsonschema.ValidationError
            gateway.call("schema-interpreter", "artefact.write", {"payload": {}}, run_id)

    def test_additional_properties_rejected(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(Exception):
            gateway.call("schema-interpreter", "artefact.write", {"kind": "x", "payload": {}, "extra": 1}, run_id)


class TestNoHandlerRegisteredYet:
    def test_repo_search_is_registered_but_not_implemented(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(NotImplementedError):
            gateway.call("repository-scout", "repo.search", {"query": "x", "repoIds": ["a"]}, run_id)


class TestArtefactWrite:
    def test_write_returns_an_artefact_ref_and_is_recorded(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        result = gateway.write("schema-interpreter", run_id, {"foo": "bar"})
        assert isinstance(result, dict)
        assert result["artefactRef"].startswith("artefact://schema-interpreter/")
        assert gateway.written == [{"kind": "schema-interpreter", "payload": {"foo": "bar"}}]

    def test_multiple_writes_get_distinct_refs(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        first = gateway.write("schema-interpreter", run_id, {"n": 1})
        second = gateway.write("schema-interpreter", run_id, {"n": 2})
        assert isinstance(first, dict) and isinstance(second, dict)
        assert first["artefactRef"] != second["artefactRef"]


class TestJournalling:
    def test_denied_call_is_journalled_as_tool_denied(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(ToolDenied):
            gateway.call("repository-scout", "acord.lookup", {"query": "x"}, run_id)

        run_store = RunStore(base_path=tmp_path)
        journal_path = run_store.run_dir(run_id) / "journal.jsonl"
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[0])
        assert event["kind"] == "tool.denied"
        assert event["agent"] == "repository-scout"
        assert event["tool"] == "acord.lookup"
        assert event["outcome"] == "failed"
        assert "not authorised" in event["detail"]

    def test_successful_call_is_journalled_as_tool_call(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        gateway.write("schema-interpreter", run_id, {})

        run_store = RunStore(base_path=tmp_path)
        journal_path = run_store.run_dir(run_id) / "journal.jsonl"
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[0])
        assert event["kind"] == "tool.call"
        assert event["tool"] == "artefact.write"
        assert event["outcome"] == "ok"

    def test_seq_increments_across_calls(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        gateway.write("schema-interpreter", run_id, {"n": 1})
        gateway.write("schema-interpreter", run_id, {"n": 2})

        run_store = RunStore(base_path=tmp_path)
        journal_path = run_store.run_dir(run_id) / "journal.jsonl"
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        seqs = [json.loads(line)["seq"] for line in lines]
        assert seqs == [0, 1]


class TestSpecParseHandler:
    def test_calls_the_real_parser_via_the_artefact_resolver(self, tmp_path: Path) -> None:
        import hashlib

        from generated.C1.SourceArtefact._1_0 import C1Sourceartefact

        content = b'{"components":{"schemas":{"Claim":{"type":"object","properties":{"claimId":{"type":"string"}}}}}}'
        content_hash = hashlib.sha256(content).hexdigest()
        artefact = C1Sourceartefact.model_validate({
            "artefactId": "art-1", "region": "uk", "system": "git", "uri": "u", "version": "v1",
            "contentHash": content_hash, "mediaType": "application/json", "evidenceTier": 1,
            "sanitisation": {
                "artefactId": "art-1", "contentHash": content_hash, "labels": ["STRUCTURAL"],
                "verdict": "allow", "licenceDisposition": "permitted", "policyVersion": 3,
                "classifiedAt": "2026-08-31T12:00:00Z",
            },
        })

        gateway = ToolGateway(
            run_store=RunStore(base_path=tmp_path),
            run_id_for_parse=uuid4(),
            artefact_resolver=lambda artefact_id: (content, artefact),
        )
        run_id = uuid4()
        result = gateway.call("schema-interpreter", "spec.parse", {"artefactId": "art-1", "format": "openapi"}, run_id)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["localName"] == "claimId"

    def test_no_resolver_configured_raises(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        run_id = uuid4()
        with pytest.raises(RuntimeError, match="artefact_resolver"):
            gateway.call("schema-interpreter", "spec.parse", {"artefactId": "art-1", "format": "openapi"}, run_id)


class TestSubstrateNotConfigured:
    def test_substrate_property_raises_when_unset(self, tmp_path: Path) -> None:
        gateway = _gateway(tmp_path)
        with pytest.raises(RuntimeError, match="SubstrateApi"):
            _ = gateway.substrate
