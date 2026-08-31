"""Section 16.4's threshold table, transcribed for the agents this repo
has actually built so far. Extended as later increments build ACORD
Aligner / Canonical Synthesiser / Adversarial Critic / Rule Extractor."""

from __future__ import annotations

THRESHOLDS: dict[str, dict[str, float]] = {
    "semantic-resolver": {
        "cluster_f1": 0.88,
        "homonym_recall": 1.00,  # "no tolerance"
    },
}
