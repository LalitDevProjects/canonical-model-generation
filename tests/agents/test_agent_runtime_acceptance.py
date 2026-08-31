"""
Increment 6's literal acceptance test (Section 17.2): "A denied tool
call is journalled and refused; a schema violation retries then
escalates; the planted injection string changes nothing."
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from generated.C11.RunManifest._1_0 import Pins

from agents.base import RunContext, WorkItem
from agents.model_gateway import Budget, ModelGateway, ProviderResponse
from agents.repository_scout import make_repository_scout_classifier
from agents.validation import WorkItemFailed
from config.settings import ModelProvider, ModelTierConfig, load_settings
from connectors.base import ConnectorScope
from connectors.confluence_connector import ConfluenceConnector
from connectors.relevance import filter_relevance
from pipeline.run_store import RunStore
from substrate.api import SubstrateApi
from substrate.db import SubstrateDb
from tools.gateway import ToolDenied, ToolGateway

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SCOUT_DIR = REPO_ROOT / "golden" / "agents" / "scout"


def _make_ctx(tmp_path: Path, *, provider: Any) -> RunContext:
    run_id = uuid4()
    run_store = RunStore(base_path=tmp_path / "run-store")
    substrate = SubstrateApi(SubstrateDb("postgresql://unused/unused"), run_store, dimensions=8, acord_ingestion_enabled=False)
    gateway = ToolGateway(run_store=run_store, run_id_for_parse=run_id)
    tier_config = {"fast": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="fast-v1", max_tokens=8000, model_id="claude-haiku-4-5-20251001")}
    model_gateway = ModelGateway(tier_config=tier_config, provider=provider)
    budget = Budget(total_tokens=1_000_000, cost_ceiling=Decimal("1000"), per_stage={})
    pins = Pins(prompts={}, models={}, tools={}, algorithms={})
    return RunContext(run_id=run_id, substrate=substrate, pins=pins, model_gateway=model_gateway, budget=budget, tools=gateway)


class TestADeniedToolCallIsJournalledAndRefused:
    def test_the_call_is_refused(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        gateway = ToolGateway(run_store=run_store, run_id_for_parse=uuid4())
        run_id = uuid4()

        # repository-scout is not in acord.lookup's own authorised-agent
        # list (only acord-aligner/canonical-synthesiser are, per Section
        # 7.2's own worked example) - an out-of-allow-list request.
        with pytest.raises(ToolDenied):
            gateway.call("repository-scout", "acord.lookup", {"query": "ClaimNumber"}, run_id)

    def test_the_attempt_is_journalled_as_tool_denied(self, tmp_path: Path) -> None:
        run_store = RunStore(base_path=tmp_path)
        gateway = ToolGateway(run_store=run_store, run_id_for_parse=uuid4())
        run_id = uuid4()

        with pytest.raises(ToolDenied):
            gateway.call("repository-scout", "acord.lookup", {"query": "ClaimNumber"}, run_id)

        journal_path = run_store.run_dir(run_id) / "journal.jsonl"
        [line] = journal_path.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(line)
        assert event["kind"] == "tool.denied"
        assert event["agent"] == "repository-scout"
        assert event["tool"] == "acord.lookup"
        assert event["outcome"] == "failed"


class TestASchemaViolationRetriesThenEscalates:
    def test_two_retries_then_the_work_item_fails(self, tmp_path: Path) -> None:
        from test_base import _FakeAgent, _write_template

        root = _write_template(tmp_path)
        calls: list[str] = []

        def provider(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
            calls.append(prompt)
            # Always invalid: missing the required "value" property -
            # Section 7.3's V1 own policy ("retry up to 2 times") plus
            # 7.6's "third failure fails the work item".
            return ProviderResponse(text="{}", tokens_in=1, tokens_out=1)

        ctx = _make_ctx(tmp_path, provider=provider)
        agent = _FakeAgent(root)
        item = WorkItem(item_id="item-1", stage="S1", kind="fake", payload={})

        with pytest.raises(WorkItemFailed):
            agent.invoke(item, ctx)

        # Original attempt + 2 retries = 3 calls, each after the first
        # carrying the validation error appended to the prompt.
        assert len(calls) == 3
        assert "[CORRECTION]" in calls[1]
        assert "[CORRECTION]" in calls[2]


class TestThePlantedInjectionStringChangesNothing:
    def test_the_injection_fixture_is_still_classified_out_of_domain(self, tmp_path: Path) -> None:
        connector = ConfluenceConnector(GOLDEN_SCOUT_DIR, region="uk")
        refs = list(connector.discover(ConnectorScope(region="uk", domain="claims")))
        [injection_ref] = [r for r in refs if r.uri.endswith("700002")]
        assert "Ignore all previous instructions" in (injection_ref.description or "")

        def respond(prompt: str) -> str:
            # A well-behaved model, honouring the [INJECTION] block,
            # classifies on genuine content and ignores the embedded
            # override entirely.
            return json.dumps({"verdicts": [
                {"uri": injection_ref.uri, "in_domain": False, "reason": "office relocation FAQ, no claims-domain signal"},
            ]})

        def provider(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
            return ProviderResponse(text=respond(prompt), tokens_in=10, tokens_out=5)

        ctx = _make_ctx(tmp_path, provider=provider)
        classifier = make_repository_scout_classifier(ctx)
        [(ref, verdict)] = list(classifier([injection_ref], "claims"))
        assert verdict.in_domain is False

    def test_end_to_end_through_filter_relevance_the_artefact_is_excluded(self, tmp_path: Path) -> None:
        connector = ConfluenceConnector(GOLDEN_SCOUT_DIR, region="uk")
        refs = list(connector.discover(ConnectorScope(region="uk", domain="claims")))

        def provider(model_id: str, prompt: str, response_schema: dict[str, Any], max_tokens: int) -> ProviderResponse:
            verdicts = [
                {"uri": ref.uri, "in_domain": False, "reason": "no genuine claims-domain content"}
                for ref in refs
            ]
            return ProviderResponse(text=json.dumps({"verdicts": verdicts}), tokens_in=10, tokens_out=5)

        ctx = _make_ctx(tmp_path, provider=provider)
        settings = load_settings()
        keep, exclusions = filter_relevance(
            refs, "claims", settings.relevance, scout_classifier=make_repository_scout_classifier(ctx),
        )

        assert keep == []
        injection_exclusion = next(e for e in exclusions if e.uri.endswith("700002"))
        assert injection_exclusion.reason == "out-of-domain"
