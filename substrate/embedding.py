"""
Mock embedding (Section 6, embedding pipeline). Increment 1 already
locked in "LLM/model gateway: provider-abstracted (tier-based, no
concrete model names anywhere), backed by a mock provider until
Increment 6" - this increment cannot call a real embedding API, so
mock_embed() stands in for it.

Neither of Increment 5's own acceptance-test clauses ("retrieval is
deterministic across repeats"; "the four-hop lineage query returns the
expected path") requires semantically meaningful embeddings - only
reproducibility. mock_embed() is therefore deliberately NOT engineered
toward real semantic quality: it is a pure function of (normalised text,
dimensions), with no randomness and no wall-clock seed, so the same
input always produces the same vector, forever, on any machine.
"""

from __future__ import annotations

import hashlib
import math

MOCK_MODEL_ID = "mock-v1"


def _normalise(text: str) -> str:
    return " ".join(text.split()).lower()


def mock_embed(text: str, *, dimensions: int) -> list[float]:
    """Repeatedly hashes SHA256(f"{normalised}|{counter}"), unpacking each
    32-byte digest into four 8-byte big-endian integers mapped to
    [-1, 1), until `dimensions` values are collected, then L2-normalises.
    Deterministic and collision-resistant enough for a mock: distinct
    input texts produce distinct vectors with overwhelming probability,
    without claiming any semantic relationship between them."""
    if dimensions <= 0:
        raise ValueError(f"dimensions must be positive, got {dimensions}")

    normalised = _normalise(text)
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{normalised}|{counter}".encode("utf-8")).digest()
        for offset in range(0, len(digest), 8):
            if len(values) >= dimensions:
                break
            as_int = int.from_bytes(digest[offset:offset + 8], "big")
            values.append((as_int / 2**64) * 2.0 - 1.0)
        counter += 1

    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def vector_literal(values: list[float]) -> str:
    """Formats a Python float list as a pgvector input literal
    ("[0.1,-0.2,...]"), passed as a bound query parameter - never
    string-interpolated into SQL - so no separate `pgvector` adapter
    package (and its numpy dependency) is needed just to format this."""
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
