from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from uuid import uuid4

import pytest

from generated.C5.AttributeRecord._1_0 import C5Attributerecord
from generated.C6.ConceptCluster._1_0 import C6Conceptcluster

from algorithms.clustering import ReviewPair, build_cluster
from algorithms.profiling import profile
from config.settings import ClusteringConfig
from eval.harness import EvalCase, EvalSet, evaluate, score_one
from eval.thresholds import THRESHOLDS

from eval_llm_fixture import anthropic_key  # used as a pytest fixture below, not called directly

RUN_ID = uuid4()
_CFG = ClusteringConfig()
_DIMS = 64


def _attr(local_name: str, data_type: str, region: str, **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://{region}/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": region,
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": [f"evref://{region}/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _sibling(region: str) -> C5Attributerecord:
    return _attr("claimId", "string", region, parentPath="Claim")


def _eval_case() -> EvalCase:
    """One deterministic auto-merge pair (lossDate/lossDate, matching
    parentPath+siblings - empirically verified to score 0.865, above
    link_threshold=0.72) plus one review-band pair (reserveAmount/
    reserveAmt - empirically verified to score 0.57, inside
    [review_band_low=0.55, link_threshold=0.72)) that only an agent
    adjudicator can resolve."""
    loss_us = profile(_attr("lossDate", "date", "us", parentPath="Claim"), siblings=[_sibling("us")])
    loss_uk = profile(_attr("lossDate", "date", "uk", parentPath="Claim"), siblings=[_sibling("uk")])
    reserve_us = profile(
        _attr("reserveAmount", "decimal", "us", constraints=[{"kind": "range", "expression": "minimum=0"}]), siblings=[],
    )
    reserve_uk = profile(
        _attr("reserveAmt", "decimal", "uk", constraints=[{"kind": "range", "expression": "minimum=0"}]), siblings=[],
    )
    return EvalCase(
        case_id="c1",
        profiled_attributes=(loss_us, loss_uk, reserve_us, reserve_uk),
        expected_cluster_groups=(
            frozenset({loss_us.record.attributeId, loss_uk.record.attributeId}),
            frozenset({reserve_us.record.attributeId, reserve_uk.record.attributeId}),
        ),
    )


_Adjudicator = Callable[[Sequence[ReviewPair]], Iterator[C6Conceptcluster]]


def _make_adjudicator_factory(*, merges_correctly: bool) -> Callable[[], _Adjudicator]:
    def factory() -> _Adjudicator:
        def _adjudicate(review_pairs: Sequence[ReviewPair]) -> Iterator[C6Conceptcluster]:
            for pair in review_pairs:
                if not merges_correctly:
                    continue  # agent declines to merge - correct members stay apart
                edges = {frozenset({pair.a.record.attributeId, pair.b.record.attributeId}): pair.score}
                yield build_cluster([pair.a, pair.b], edges=edges, conflict_class=None, conflict_detail=None)
        return _adjudicate
    return factory


class TestScoreOne:
    def test_correct_adjudicator_scores_perfect_f1(self) -> None:
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        scores = score_one(
            eval_set, adjudicate_factory=_make_adjudicator_factory(merges_correctly=True), config=_CFG, embed_dimensions=_DIMS,
        )
        assert scores["cluster_f1"] == 1.0

    def test_declining_adjudicator_scores_imperfect_f1(self) -> None:
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        scores = score_one(
            eval_set, adjudicate_factory=_make_adjudicator_factory(merges_correctly=False), config=_CFG, embed_dimensions=_DIMS,
        )
        assert 0.0 < scores["cluster_f1"] < 1.0  # the deterministic pair still contributes a true positive

    def test_homonym_recall_is_one_when_nothing_expected(self) -> None:
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        scores = score_one(
            eval_set, adjudicate_factory=_make_adjudicator_factory(merges_correctly=True), config=_CFG, embed_dimensions=_DIMS,
        )
        assert scores["homonym_recall"] == 1.0

    def test_homonym_recall_penalised_when_the_agent_wrongly_merges_a_planted_homonym(self) -> None:
        # Matching parentPath+siblings (like the golden clustering
        # fixtures) empirically scores 0.665 - inside the review band, so
        # this pair genuinely reaches the adjudicator rather than being
        # auto-merged or dropped before it gets a chance.
        us = profile(_attr("claimDate", "dateTime", "uk", parentPath="Claim"), siblings=[_sibling("uk")])
        eu = profile(_attr("claimDate", "string", "eu", parentPath="Claim"), siblings=[_sibling("eu")])
        case = EvalCase(
            case_id="homonym-case",
            profiled_attributes=(us, eu),
            expected_cluster_groups=(),
            expected_homonym_pairs=(frozenset({us.record.attributeId, eu.record.attributeId}),),
        )
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(case,))

        def bad_factory() -> _Adjudicator:
            def _adjudicate(review_pairs: Sequence[ReviewPair]) -> Iterator[C6Conceptcluster]:
                for pair in review_pairs:
                    edges = {frozenset({pair.a.record.attributeId, pair.b.record.attributeId}): pair.score}
                    yield build_cluster([pair.a, pair.b], edges=edges, conflict_class=None, conflict_detail=None)
            return _adjudicate

        scores = score_one(eval_set, adjudicate_factory=bad_factory, config=_CFG, embed_dimensions=_DIMS)
        assert scores["homonym_recall"] == 0.0

    def test_homonym_recall_credited_when_the_agent_correctly_declines_to_merge(self) -> None:
        us = profile(_attr("claimDate", "dateTime", "uk", parentPath="Claim"), siblings=[_sibling("uk")])
        eu = profile(_attr("claimDate", "string", "eu", parentPath="Claim"), siblings=[_sibling("eu")])
        case = EvalCase(
            case_id="homonym-case-correct",
            profiled_attributes=(us, eu),
            expected_homonym_pairs=(frozenset({us.record.attributeId, eu.record.attributeId}),),
        )
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(case,))

        scores = score_one(
            eval_set, adjudicate_factory=_make_adjudicator_factory(merges_correctly=False), config=_CFG, embed_dimensions=_DIMS,
        )
        assert scores["homonym_recall"] == 1.0


class TestEvaluate:
    def test_worst_of_five_gating_catches_a_single_bad_run(self) -> None:
        """A scripted factory that merges correctly on 4 of 5 repeats and
        declines on the 5th must fail the gate (worst, not mean) even
        though the mean F1 would pass."""
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        call_count = {"n": 0}

        def flaky_factory() -> _Adjudicator:
            call_count["n"] += 1
            merges_correctly = call_count["n"] != 5

            def _adjudicate(review_pairs: Sequence[ReviewPair]) -> Iterator[C6Conceptcluster]:
                for pair in review_pairs:
                    if not merges_correctly:
                        continue
                    edges = {frozenset({pair.a.record.attributeId, pair.b.record.attributeId}): pair.score}
                    yield build_cluster([pair.a, pair.b], edges=edges, conflict_class=None, conflict_detail=None)
            return _adjudicate

        results = evaluate(
            "semantic-resolver", eval_set, adjudicate_factory=flaky_factory, config=_CFG, embed_dimensions=_DIMS, n_repeats=5,
        )

        assert results["cluster_f1"].mean > results["cluster_f1"].worst
        assert results["cluster_f1"].passed is False
        assert results["cluster_f1"].worst < THRESHOLDS["semantic-resolver"]["cluster_f1"]

    def test_always_correct_adjudicator_passes_the_gate(self) -> None:
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        results = evaluate(
            "semantic-resolver", eval_set,
            adjudicate_factory=_make_adjudicator_factory(merges_correctly=True),
            config=_CFG, embed_dimensions=_DIMS, n_repeats=5,
        )
        assert results["cluster_f1"].passed is True
        assert results["cluster_f1"].worst == 1.0
        assert results["cluster_f1"].stdev == 0.0

    def test_returns_one_result_per_threshold_metric(self) -> None:
        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        results = evaluate(
            "semantic-resolver", eval_set,
            adjudicate_factory=_make_adjudicator_factory(merges_correctly=True),
            config=_CFG, embed_dimensions=_DIMS, n_repeats=3,
        )
        assert set(results) == set(THRESHOLDS["semantic-resolver"])
        assert all(len(r.runs) == 3 for r in results.values())


class _FakeSubstrateApi:
    """No DB dependency for this real-model test - doc_chunks are
    supplementary context, not what's under test here (the real
    Anthropic call path is)."""

    def search(self, run_id: str, query: str, **kwargs: object) -> list[object]:
        return []


class TestRealSemanticResolverEval:
    @pytest.mark.llm
    def test_evaluate_against_a_real_model_produces_real_scores(self, tmp_path: Path, anthropic_key: str) -> None:
        from decimal import Decimal

        from generated.C11.RunManifest._1_0 import Pins

        from agents.base import RunContext
        from agents.model_gateway import Budget, ModelGateway
        from agents.semantic_resolver import SemanticResolverAgent, make_semantic_resolver_adjudicator
        from config.settings import ModelProvider, ModelTierConfig
        from pipeline.run_store import RunStore
        from tools.gateway import ToolGateway

        run_store = RunStore(base_path=tmp_path / "run-store")
        model_gateway = ModelGateway(tier_config={
            "high": ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="high-v1", max_tokens=4096, model_id="claude-sonnet-5"),
        })
        budget = Budget(total_tokens=200_000, cost_ceiling=Decimal("10"), per_stage={})
        pins = Pins(prompts={"semantic-resolver": "2.3.0"}, models={}, tools={}, algorithms={})
        ctx = RunContext(
            run_id=RUN_ID, substrate=_FakeSubstrateApi(), pins=pins,  # type: ignore[arg-type]
            model_gateway=model_gateway, budget=budget, tools=ToolGateway(run_store=run_store, run_id_for_parse=RUN_ID),
        )

        def factory() -> _Adjudicator:
            return make_semantic_resolver_adjudicator(ctx, agent=SemanticResolverAgent(), run_store=run_store)

        eval_set = EvalSet(agent_id="semantic-resolver", cases=(_eval_case(),))
        results = evaluate("semantic-resolver", eval_set, adjudicate_factory=factory, config=_CFG, embed_dimensions=_DIMS, n_repeats=1)

        assert 0.0 <= results["cluster_f1"].worst <= 1.0
        assert 0.0 <= results["homonym_recall"].worst <= 1.0
