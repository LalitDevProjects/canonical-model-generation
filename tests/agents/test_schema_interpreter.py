from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from generated.C1.SourceArtefact._1_0 import C1Sourceartefact
from generated.C11.RunManifest._1_0 import Pins

from agents.base import RunContext, WorkItem
from agents.model_gateway import Budget, ModelGateway
from agents.schema_interpreter import SchemaInterpreterAgent, _guardrail_every_record_has_evidence
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from tools.gateway import ToolGateway

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_XSD = REPO_ROOT / "golden" / "xsd" / "uk" / "ClaimNotification.xsd"


def _artefact(content: bytes, artefact_id: str = "art-xsd") -> C1Sourceartefact:
    content_hash = hashlib.sha256(content).hexdigest()
    return C1Sourceartefact.model_validate({
        "artefactId": artefact_id, "region": "uk", "system": "git", "uri": "u", "version": "v1",
        "contentHash": content_hash, "mediaType": "application/xml", "evidenceTier": 1,
        "sanitisation": {
            "artefactId": artefact_id, "contentHash": content_hash, "labels": ["STRUCTURAL"],
            "verdict": "allow", "licenceDisposition": "permitted", "policyVersion": 3,
            "classifiedAt": "2026-08-31T12:00:00Z",
        },
    })


def _make_ctx(tmp_path: Path, *, content: bytes, artefact: C1Sourceartefact) -> RunContext:
    run_id = uuid4()
    run_store = RunStore(base_path=tmp_path / "run-store")
    substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
    gateway = ToolGateway(
        run_store=run_store, run_id_for_parse=run_id,
        artefact_resolver=lambda artefact_id: (content, artefact),
    )
    model_gateway = ModelGateway(tier_config={}, provider=lambda *a: (_ for _ in ()).throw(AssertionError("n/a agent must not call the model")))
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={}, models={}, tools={}, algorithms={})
    return RunContext(run_id=run_id, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)


class TestSchemaInterpreterAgent:
    def test_parses_the_real_golden_xsd_fixture(self, tmp_path: Path) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = _artefact(content)
        ctx = _make_ctx(tmp_path, content=content, artefact=artefact)
        agent = SchemaInterpreterAgent()
        item = WorkItem(item_id="art-xsd", stage="S2", kind="parse", payload={"artefactId": "art-xsd", "format": "xsd"})

        result = agent.invoke(item, ctx)

        assert result.outcome == "ok"
        assert len(result.output["attributes"]) > 0
        local_names = {a["localName"] for a in result.output["attributes"]}
        assert "claimReferenceCode" in local_names

    def test_never_calls_the_model_gateway(self, tmp_path: Path) -> None:
        # The injected provider in _make_ctx raises AssertionError if
        # ever called - this test passing at all IS the assertion.
        content = GOLDEN_XSD.read_bytes()
        artefact = _artefact(content)
        ctx = _make_ctx(tmp_path, content=content, artefact=artefact)
        agent = SchemaInterpreterAgent()
        item = WorkItem(item_id="art-xsd", stage="S2", kind="parse", payload={"artefactId": "art-xsd", "format": "xsd"})
        agent.invoke(item, ctx)

    def test_writes_the_output_via_the_tool_gateway(self, tmp_path: Path) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = _artefact(content)
        ctx = _make_ctx(tmp_path, content=content, artefact=artefact)
        agent = SchemaInterpreterAgent()
        item = WorkItem(item_id="art-xsd", stage="S2", kind="parse", payload={"artefactId": "art-xsd", "format": "xsd"})

        agent.invoke(item, ctx)

        assert len(ctx.tools.written) == 1
        assert ctx.tools.written[0]["kind"] == "schema-interpreter"

    def test_every_evidence_ref_resolves_to_the_parsed_artefact(self, tmp_path: Path) -> None:
        content = GOLDEN_XSD.read_bytes()
        artefact = _artefact(content, artefact_id="art-xsd-2")
        ctx = _make_ctx(tmp_path, content=content, artefact=artefact)
        agent = SchemaInterpreterAgent()
        item = WorkItem(item_id="art-xsd-2", stage="S2", kind="parse", payload={"artefactId": "art-xsd-2", "format": "xsd"})

        result = agent.invoke(item, ctx)

        for record in result.output["attributes"]:
            for ref in record["evidenceRefs"]:
                assert "art-xsd-2" in ref

    def test_no_guardrail_violation_for_real_parser_output(self, tmp_path: Path) -> None:
        # parsers/record_builder.py always sets a non-empty evidenceRefs -
        # G1 should never fire against real parser output.
        content = GOLDEN_XSD.read_bytes()
        artefact = _artefact(content)
        ctx = _make_ctx(tmp_path, content=content, artefact=artefact)
        agent = SchemaInterpreterAgent()
        item = WorkItem(item_id="art-xsd", stage="S2", kind="parse", payload={"artefactId": "art-xsd", "format": "xsd"})

        result = agent.invoke(item, ctx)
        assert result.outcome == "ok"


class TestGuardrailDirectly:
    """The guardrail's own violation branch is expected to never fire
    against real parser output (parsers/record_builder.py always sets a
    non-empty evidenceRefs) - exercised directly against a hand-crafted
    payload instead, to prove the guardrail logic itself is correct, not
    just currently unreachable."""

    def test_missing_evidence_refs_is_flagged(self) -> None:
        output = {"attributes": [{"attributeId": "attr://uk/x/y", "evidenceRefs": []}]}
        violations = _guardrail_every_record_has_evidence(output, ctx=None)  # type: ignore[arg-type]
        assert len(violations) == 1
        assert violations[0].code == "G1-missing-evidence"

    def test_present_evidence_refs_are_not_flagged(self) -> None:
        output = {"attributes": [{"attributeId": "attr://uk/x/y", "evidenceRefs": ["evref://uk/git/x@abc#/y"]}]}
        assert _guardrail_every_record_has_evidence(output, ctx=None) == []  # type: ignore[arg-type]


class TestValidateSemanticsBeforeCompute:
    def test_returns_no_violations_when_called_before_compute_has_run(self) -> None:
        # A defensive guard: validate_semantics() reads self._current_artefact_id,
        # set by compute() - calling it on a fresh instance (compute()
        # never run) must not crash.
        agent = SchemaInterpreterAgent()
        assert agent.validate_semantics({"attributes": []}, ctx=None) == []  # type: ignore[arg-type]
