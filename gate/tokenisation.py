"""
Tokenisation (Section 5.3): "Deterministic, keyed, and irreversible
outside the region. The central platform can tell that two occurrences
are the same entity - which preserves the co-reference signal that
clustering needs - but cannot recover the value. The key never leaves the
region."

Key custody (verbatim): "Region tokenisation keys live in the regional
key store only. They MUST NOT be replicated to the central platform under
any circumstance." This repo has no such regional key-store
infrastructure - config.egress.tokenisation_keys is a committed PoC
placeholder standing in for it (see config/settings.py's EgressConfig
docstring), not production key material.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence

from config.settings import EgressConfig
from gate.detectors import Span
from gate.structure import ParsedDocument


def tokenise(value: str, label: str, region_key: bytes) -> str:
    """Exactly the spec's own pseudocode (Section 5.3). "Label prefixing
    keeps the token type visible to downstream analysis without
    revealing the value." """
    digest = hmac.new(region_key, f"{label}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"<{label}:{digest}>"


def region_key_bytes(region: str, cfg: EgressConfig) -> bytes:
    """Fails closed on a missing/malformed key (KeyError/ValueError),
    consistent with egress.fail_mode='closed' - never silently falls back
    to an empty or default key."""
    return bytes.fromhex(cfg.tokenisation_keys[region])


_MASK_RUNGS = {"L1", "L2", "L3"}


def redact(content: bytes, spans: Sequence[Span], region_key: bytes, structured: ParsedDocument | None) -> bytes:
    """Deterministic substring replace-all over the ORIGINAL raw bytes -
    not path-based mutation of a re-parsed/re-serialized structure. This
    is deliberate: yaml.safe_dump/json.dumps do not reproduce the
    original byte formatting (key order, quoting, comments), so
    re-serializing every admitted artefact - including the overwhelming
    majority with nothing to redact - would silently change contentHash
    for artefacts that were never actually touched. Structural
    identification (gate/structure.py) is still used to find WHAT counts
    as an example/prose value; redaction itself just replaces those exact
    matched strings wherever they occur in the real bytes.

    The `structured` parameter is currently unused in the body - kept in
    the signature since a future increment wanting format-preserving,
    offset-aware redaction (e.g. via a round-tripping YAML library) would
    need it; accepted as a documented PoC limitation for now, same
    honesty standard as the L2 heuristic.
    """
    mask_spans = [s for s in spans if s.rung.value in _MASK_RUNGS]
    if not mask_spans:
        return content

    text = content.decode("utf-8")
    unique_values = {(s.value, s.label.value) for s in mask_spans}
    # Longest-value-first, deliberately: an L3 example value routinely
    # CONTAINS an L1/L2 sub-match (e.g. the example "A. Smith, SW1A 1AA"
    # is itself flagged whole by L3 as SAMPLE_VALUE, while "SW1A 1AA"
    # and "A. Smith" are independently flagged by L1/L2 as IDENTIFYING).
    # Replacing the longest span first consumes the shorter ones inside
    # it - their own .replace() calls simply find nothing left to match,
    # which is correct: the raw PII is gone either way, and a second,
    # separate token for a substring already covered by a broader token
    # would be redundant, not safer. Detection (the `labels` set used for
    # policy/C2, computed before redaction) is unaffected by this
    # consolidation - both SAMPLE_VALUE and IDENTIFYING still appear
    # there, this is purely about how many literal token markers land in
    # the redacted text.
    for value, label in sorted(unique_values, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(value, tokenise(value, label, region_key))
    return text.encode("utf-8")
