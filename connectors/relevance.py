"""
Relevance filtering (Section 4.2).

"An estate of several hundred endpoints and a hundred or more repositories
contains far more irrelevant than relevant material. Filtering runs in two
passes, and both passes MUST record their exclusions into
CorpusManifest.exclusions." "Note that drop is returned, not discarded:
every exclusion is a recorded decision with an author."

Pass 1 (this module, in full) is deterministic: score four signals per
artefact, combine them with configured weights, and bucket the result
against pass1_keep/pass1_drop thresholds. Pass 2 in the spec is the
Repository Scout agent, which "reads headers, titles and descriptions
only" to resolve whatever pass 1 was uncertain about - but agents don't
land until Increment 6 (sequencing rule: "Deterministic before
probabilistic. I3 lands before I6, so that model output is never the only
path to a result"). Increment 2's interim stand-in for pass 2 is
default_uncertain_policy (see its docstring for the confirmed keep-with-
warning decision); scout_classifier is a real parameter specifically so
Increment 6 can swap in the actual Repository Scout without touching this
function's signature.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Iterator, Sequence

from generated.common.defs import ExclusionEntry, ExclusionReason

from config.settings import RelevanceConfig
from connectors.base import ArtefactRef

logger = logging.getLogger(__name__)

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def score_tokens(uri: str, tokens: Sequence[str]) -> float:
    """1.0 if any configured domain token is a substring of any word in the
    (lowercased, punctuation-split) uri, else 0.0.

    A match-proportion (matches / len(tokens)) was considered and rejected:
    domain_tokens["claims"] has 8 entries, and a real artefact path
    typically contains at most one or two of them, so a ratio would almost
    never clear pass1_keep for anything. Substring rather than exact-word
    equality so "claims" matches the configured token "claim" - documented,
    accepted false-positive risk (e.g. "unclaimed" would also match) for a
    first-pass deterministic heuristic, not tuned further at Increment 2.
    """
    if not tokens:
        return 0.0
    words = [w for w in _TOKEN_SPLIT_RE.split(uri.lower()) if w]
    return 1.0 if any(token.lower() in word for token in tokens for word in words) else 0.0


def weighted(signals: dict[str, float], weights: dict[str, float]) -> float:
    """Dot product of signals against weights. Weights are expected to
    already sum to ~1.0 (RelevanceConfig carries no such constraint, since
    the spec gives no pass1_weights example to validate against) so the
    result stays directly comparable to the 0..1-scaled pass1_keep/
    pass1_drop thresholds; no renormalisation is performed here."""
    return sum(signals[key] * weights.get(key, 0.0) for key in signals)


class ScoutVerdict:
    """A pass-2 classification result for one previously-uncertain
    ArtefactRef. Mirrors the spec pseudocode's scout_agent.classify(...)
    verdict shape (in_domain, reason)."""

    __slots__ = ("in_domain", "reason")

    def __init__(self, in_domain: bool, reason: str) -> None:
        self.in_domain = in_domain
        self.reason = reason


def default_uncertain_policy(
    uncertain: list[ArtefactRef], domain: str
) -> Iterator[tuple[ArtefactRef, ScoutVerdict]]:
    """Increment 2's interim stand-in for scout_agent.classify (the
    Repository Scout agent does not exist until Increment 6).

    Confirmed decision: default every uncertain artefact to KEPT, not
    excluded. The C4 CorpusManifest schema's own description warns "a
    silently excluded source is indistinguishable from an absent one" -
    excluding by default here would mean borderline material disappears
    for a reason nothing has actually judged, which is exactly that
    failure mode. Recording it as reason="manual" (the alternative
    considered) would misattribute an automated default as a human
    decision, which is worse than the audit gap defaulting-to-keep leaves.
    Each kept item is logged individually so the deferral stays visible
    even though the closed C1/C4 schemas have no field to record it inside
    the sealed manifest itself.
    """
    for ref in uncertain:
        yield ref, ScoutVerdict(
            in_domain=True,
            reason=(
                "pass1 uncertain; no Repository Scout until Increment 6, "
                "defaulting to inclusion (evidence-completeness over silent exclusion)"
            ),
        )


def filter_relevance(
    refs: Sequence[ArtefactRef],
    domain: str,
    cfg: RelevanceConfig,
    scout_classifier: Callable[
        [list[ArtefactRef], str], Iterable[tuple[ArtefactRef, ScoutVerdict]]
    ] = default_uncertain_policy,
) -> tuple[list[ArtefactRef], list[ExclusionEntry]]:
    """Two-pass relevance filtering. Returns (keep, exclusions) - drop is
    never silently discarded, matching the spec's own framing."""
    keep: list[ArtefactRef] = []
    uncertain: list[ArtefactRef] = []
    exclusions: list[ExclusionEntry] = []

    for ref in refs:
        signals = {
            "path": score_tokens(ref.uri, cfg.domain_tokens.get(domain, [])),
            "catalogue": 1.0 if ref.catalogue_domain == domain else 0.0,
            "gateway": 1.0 if ref.has_live_route else 0.0,
            "kind": 1.0 if ref.media_type in cfg.contract_media_types else 0.3,
        }
        score = weighted(signals, cfg.pass1_weights)
        if score >= cfg.pass1_keep:
            keep.append(ref)
        elif score <= cfg.pass1_drop:
            exclusions.append(ExclusionEntry(
                uri=ref.uri,
                reason=ExclusionReason.out_of_domain,
                detail=f"pass1 score {score:.2f}",
                decidedBy="pass1",
            ))
        else:
            uncertain.append(ref)

    for ref, verdict in scout_classifier(uncertain, domain):
        if verdict.in_domain:
            keep.append(ref)
            logger.warning("relevance: %r kept via uncertain-band default policy (%s)", ref.uri, verdict.reason)
        else:
            exclusions.append(ExclusionEntry(
                uri=ref.uri,
                reason=ExclusionReason.out_of_domain,
                detail=verdict.reason,
                decidedBy="repository-scout",
            ))

    return keep, exclusions
