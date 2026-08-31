"""
Agent evaluation harness (Section 16.4): "Agents are evaluated, not
asserted. Each agent has an evaluation set drawn from the golden corpus
with expected outcomes agreed by a human, and a threshold that MUST be
met for a prompt or model change to be promoted." eval/ was populated at
Increment 6/7 per its own README - Increment 6 deferred it (no
thresholds existed for its own two agents); Increment 7 is where real
thresholds finally exist (eval/thresholds.py), for Semantic Resolver.

evaluate()/score_one() run the FULL clustering pipeline (deterministic
auto-merge + agent adjudication of the review-band material it sets
aside) over an eval set and compare against each case's human-agreed
expected outcome - not the agent in isolation, because that's what a
real deployment actually produces. Gating is on the WORST of n_repeats
runs, not the mean, per Section 16.4's own literal evaluate() pseudocode
("the workshop sees one run, not an average").

Running 5 REAL Anthropic calls per eval case isn't reachable this
session (no API key - the same, still-current Increment 6 constraint).
evaluate()/score_one()'s own arithmetic (F1, homonym recall, worst-of-5
gating) is proven hermetically here against a scripted, injectable
adjudicator factory; a real end-to-end run against a live model is
pytest.mark.llm and skips cleanly without a key.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from generated.C6.ConceptCluster._1_0 import C6Conceptcluster

from algorithms.clustering import ReviewPair, run_clustering
from algorithms.profiling import ProfiledAttribute
from config.settings import ClusteringConfig
from eval.thresholds import THRESHOLDS

AdjudicatorFactory = Callable[[], Callable[[Sequence[ReviewPair]], Iterator[C6Conceptcluster]]]


@dataclass(frozen=True)
class EvalCase:
    """One golden-corpus case with a human-agreed expected outcome.
    expected_cluster_groups: sets of attributeIds that SHOULD end up in
    the same cluster. expected_homonym_pairs: attributeId pairs that
    MUST NEVER end up in the same cluster - Section 16.4's "no
    tolerance" homonym-recall metric is scored against these."""

    case_id: str
    profiled_attributes: tuple[ProfiledAttribute, ...]
    expected_cluster_groups: tuple[frozenset[str], ...] = ()
    expected_homonym_pairs: tuple[frozenset[str], ...] = ()


@dataclass(frozen=True)
class EvalSet:
    agent_id: str
    cases: tuple[EvalCase, ...]


@dataclass(frozen=True)
class EvalResult:
    metric: str
    mean: float
    stdev: float
    worst: float
    passed: bool
    runs: tuple[float, ...]


def _member_ids(cluster: C6Conceptcluster) -> list[str]:
    return sorted(str(m.attributeId) for m in cluster.members)


def _pairs_from_id_lists(id_lists: Sequence[Sequence[str]]) -> frozenset[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for ids in id_lists:
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add(frozenset({ids[i], ids[j]}))
    return frozenset(pairs)


def score_one(
    eval_set: EvalSet,
    *,
    adjudicate_factory: AdjudicatorFactory,
    config: ClusteringConfig,
    embed_dimensions: int,
) -> dict[str, float]:
    """One full pass over every case in the eval set. Cluster F1:
    pairwise precision/recall over "these two attributeIds ended up in
    the same cluster" against expected_cluster_groups. Homonym recall:
    the fraction of expected_homonym_pairs that genuinely never co-occur
    in a predicted cluster."""
    true_positive = false_positive = false_negative = 0
    homonym_total = homonym_correct = 0

    for case in eval_set.cases:
        clusters, review_pairs = run_clustering(
            list(case.profiled_attributes), config=config, embed_dimensions=embed_dimensions,
        )
        agent_clusters = list(adjudicate_factory()(review_pairs))
        all_clusters = [*clusters, *agent_clusters]

        predicted_pairs = _pairs_from_id_lists([_member_ids(c) for c in all_clusters])
        expected_pairs = _pairs_from_id_lists([sorted(group) for group in case.expected_cluster_groups])
        true_positive += len(predicted_pairs & expected_pairs)
        false_positive += len(predicted_pairs - expected_pairs)
        false_negative += len(expected_pairs - predicted_pairs)

        for pair in case.expected_homonym_pairs:
            homonym_total += 1
            if pair not in predicted_pairs:
                homonym_correct += 1

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 1.0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 1.0
    cluster_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    homonym_recall = homonym_correct / homonym_total if homonym_total else 1.0

    return {"cluster_f1": cluster_f1, "homonym_recall": homonym_recall}


def evaluate(
    agent_id: str,
    eval_set: EvalSet,
    *,
    adjudicate_factory: AdjudicatorFactory,
    config: ClusteringConfig,
    embed_dimensions: int,
    n_repeats: int = 5,
) -> dict[str, EvalResult]:
    """Section 16.4's evaluate(): "Repeat to measure variance, not just
    the mean. An agent whose F1 is 0.90 on average but ranges 0.72-0.98
    is not fit for use, because a single run is what actually reaches a
    workshop." Gates on the WORST observed run per metric, not the mean.
    Returns one EvalResult per threshold this agent has (Section 16.4's
    own pseudocode gates on a single scalar; Semantic Resolver has two
    named metrics, so this evaluates each independently rather than
    collapsing them into one number)."""
    thresholds = THRESHOLDS[agent_id]
    runs = [
        score_one(eval_set, adjudicate_factory=adjudicate_factory, config=config, embed_dimensions=embed_dimensions)
        for _ in range(n_repeats)
    ]
    results: dict[str, EvalResult] = {}
    for metric, threshold in thresholds.items():
        values = tuple(run[metric] for run in runs)
        worst = min(values)
        results[metric] = EvalResult(
            metric=metric,
            mean=statistics.mean(values),
            stdev=statistics.pstdev(values),
            worst=worst,
            passed=worst >= threshold,
            runs=values,
        )
    return results
