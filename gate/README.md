# gate

Populated at Increment 4. Detection -> masking -> policy decision -> ledger
- everything `connectors/manifest.py` needs to genuinely classify, redact
and admit-or-reject a fetched artefact, replacing the Increment 2
placeholder (`verdict=allow`, unconditionally).

- `structure.py` - `parse_structure`: a lightweight structural walk,
  independent of `parsers/` (the gate runs during S1, before an artefact
  is known to be kept; `parsers/` runs later, only on kept artefacts, to
  produce `AttributeRecord`s - a different concern). Classifies text by
  WHERE it sits: grammar-position (`structural_texts`, e.g. dict keys, XSD
  element names), example-position (`example_texts`), and everything else
  free-text (`prose_texts`).
- `detectors.py` - the L0-L4 classification ladder (Section 5.2). L0
  (grammar position -> `STRUCTURAL`), L1 (9 regex patterns - NI number,
  SSN, IBAN + Luhn, UK postcode, US ZIP+4, email, E.164 phone,
  DOB-in-context -> `IDENTIFYING`), L2 (Title-Case heuristic, a confirmed
  stdlib-only decision, not spaCy -> `IDENTIFYING`), L3 (positional, every
  example/default/const value -> `SAMPLE_VALUE`), L4 (curated lexicon
  -> `SENSITIVE_DOMAIN`). L5 (licence/IP) is NOT here - it's a direct
  `licenceDisposition` lookup in `connectors/manifest.py`, not a content
  detector. "The ladder runs to completion - it does not short-circuit."
- `tokenisation.py` - `tokenise()` exactly per the spec's own Section 5.3
  pseudocode (HMAC-SHA256, label-prefixed, 16-hex-char digest); `redact()`,
  a deterministic substring replace-all over the ORIGINAL raw bytes (not a
  re-serialized structure - avoids gratuitous formatting drift on the
  overwhelming majority of artefacts that need no redaction at all).
- `policy.py` + `policy.yaml` - the policy decision point (Section 5.4),
  its own versioned file (not a `config/platform.yaml` section).
  `evaluate_policy` evaluates every rule, not first-match-wins by list
  order, so a matching block rule always wins over a matching allow rule -
  see the module docstring for the real bug this caught.
- `ledger.py` - `append_ledger_entry` exactly per Section 5.5's
  `append_ledger()` pseudocode; `LedgerStore`, append-only WORM
  persistence at `ledger/{region}/entries.jsonl`.
- `evidence_store.py` - `EvidenceStore`, a minimal content-addressed
  writer at `evidence-store/artefacts/{sha256[0:2]}/{sha256}` (built now,
  a confirmed Increment 4 scope call, not deferred to Increment 5).
- `gate.py` - `classify_and_redact`: the orchestrator tying every module
  above together into the single call `connectors/manifest.py` makes once
  per kept `ArtefactRef`. Its own module docstring documents the real
  reconciliation this repo needed between the spec's two different
  verdict mechanisms (Section 5.1's ladder `block > mask > allow` vs.
  Section 5.4's policy YAML, which never produces `mask`) - read it before
  touching verdict logic anywhere in this package.

See `docs/increments.md` for what Increment 4 built and verified, and
`docs/contracts.md` for the `exclusionReason` contract change
(`"policy-blocked"`) this increment required.
