from __future__ import annotations

import logging

import pytest

from config.settings import RelevanceConfig
from connectors.base import ArtefactRef
from connectors.relevance import ScoutVerdict, filter_relevance, score_tokens, weighted


def _cfg(**overrides: object) -> RelevanceConfig:
    defaults: dict[str, object] = {
        "pass1_keep": 0.65,
        "pass1_drop": 0.20,
        "domain_tokens": {"claims": ["claim", "fnol", "loss"]},
        "pass1_weights": {"path": 0.60, "catalogue": 0.20, "gateway": 0.10, "kind": 0.10},
        "contract_media_types": ["application/yaml", "application/json"],
    }
    defaults.update(overrides)
    return RelevanceConfig.model_validate(defaults)


class TestScoreTokens:
    def test_substring_match_scores_one(self) -> None:
        assert score_tokens("git://repo/claims-us/openapi.yaml", ["claim"]) == 1.0

    def test_no_match_scores_zero(self) -> None:
        assert score_tokens("git://repo/cafeteria/menu.yaml", ["claim"]) == 0.0

    def test_empty_token_list_scores_zero(self) -> None:
        assert score_tokens("git://repo/claims-us/openapi.yaml", []) == 0.0

    def test_documented_false_positive_accepted(self) -> None:
        # "unclaimed" contains "claim" as a substring - a known, accepted
        # limitation of the first-pass heuristic, not a bug.
        assert score_tokens("git://repo/unclaimed-assets/spec.yaml", ["claim"]) == 1.0


class TestWeighted:
    def test_dot_product(self) -> None:
        signals = {"path": 1.0, "catalogue": 0.0, "gateway": 0.0, "kind": 1.0}
        weights = {"path": 0.6, "catalogue": 0.2, "gateway": 0.1, "kind": 0.1}
        assert weighted(signals, weights) == 0.7

    def test_missing_weight_defaults_to_zero_contribution(self) -> None:
        assert weighted({"path": 1.0}, {}) == 0.0


class TestFilterRelevance:
    def _ref(self, uri: str, media_type: str = "application/yaml") -> ArtefactRef:
        return ArtefactRef(uri=uri, system="git", region="us", media_type=media_type)

    def test_high_scoring_ref_is_kept(self) -> None:
        ref = self._ref("git://repo/claims-us/openapi.yaml")
        keep, exclusions = filter_relevance([ref], "claims", _cfg())
        assert keep == [ref]
        assert exclusions == []

    def test_low_scoring_ref_is_dropped_with_reason(self) -> None:
        ref = self._ref("git://repo/cafeteria/menu.yaml")
        keep, exclusions = filter_relevance([ref], "claims", _cfg())
        assert keep == []
        assert len(exclusions) == 1
        assert exclusions[0].uri == ref.uri
        assert exclusions[0].reason == "out-of-domain"
        assert exclusions[0].decidedBy == "pass1"
        assert exclusions[0].detail is not None and "pass1 score" in exclusions[0].detail

    def test_uncertain_ref_defaults_to_kept(self) -> None:
        # media_type not in contract_media_types -> kind signal 0.3, giving
        # a score strictly between pass1_drop and pass1_keep for a
        # path-matching ref.
        ref = self._ref("git://repo/claims-uk/notes.txt", media_type="text/plain")
        keep, exclusions = filter_relevance([ref], "claims", _cfg())
        assert keep == [ref]
        assert exclusions == []

    def test_uncertain_ref_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        ref = self._ref("git://repo/claims-uk/notes.txt", media_type="text/plain")
        with caplog.at_level(logging.WARNING):
            filter_relevance([ref], "claims", _cfg())
        assert any("uncertain-band default policy" in record.message for record in caplog.records)

    def test_custom_scout_classifier_can_drop_uncertain(self) -> None:
        ref = self._ref("git://repo/claims-uk/notes.txt", media_type="text/plain")

        def drop_everything(uncertain: list[ArtefactRef], domain: str) -> list[tuple[ArtefactRef, ScoutVerdict]]:
            return [(r, ScoutVerdict(in_domain=False, reason="test override")) for r in uncertain]

        keep, exclusions = filter_relevance([ref], "claims", _cfg(), scout_classifier=drop_everything)
        assert keep == []
        assert len(exclusions) == 1
        assert exclusions[0].decidedBy == "repository-scout"
        assert exclusions[0].detail == "test override"

    def test_empty_refs_produces_empty_result(self) -> None:
        keep, exclusions = filter_relevance([], "claims", _cfg())
        assert keep == []
        assert exclusions == []

    def test_unknown_domain_scores_path_signal_zero(self) -> None:
        ref = self._ref("git://repo/claims-us/openapi.yaml")
        keep, exclusions = filter_relevance([ref], "unknown-domain", _cfg())
        assert keep == []
        assert len(exclusions) == 1
