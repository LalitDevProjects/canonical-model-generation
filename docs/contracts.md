# Contract Reference (Section 3)

Source of truth: `TECHNICAL_SPECIFICATION.txt`, Section 3 (Data Contracts).
This page tracks the current implementation against it and is updated in
the same PR as any change to `contracts/` (Definition of Done, Section
17.5).

## Identity schemes

Two URI schemes, both deterministic - never a random UUID:

- `evref://{region}/{system}/{artefactId}@{contentHash}#{locator}` - a
  reference to evidence (a specific location within a source artefact)
- `attr://{region}/{contractId}/{normalisedPath}` - an attribute's own
  identity

`contracts/common/defs.json` defines both patterns, tightened slightly
beyond the spec's own literal loose check (still accepts every example the
spec gives) to catch structurally malformed URIs at schema-validation time.

## Contracts

| ID | Name | Schema path | Status |
|----|------|-------------|--------|
| C1 | SourceArtefact | `contracts/C1/SourceArtefact/1.0.json` | Extracted from C4's embedded artefact object into its own `$ref`-able schema (spec embeds it inline; this is a structural choice for single-source-of-truth generation, not a spec requirement) |
| C2 | SanitisationRecord | `contracts/C2/SanitisationRecord/1.0.json` | **Interpreted, not verbatim spec** - no JSON Schema or exhaustive field list exists in the spec; synthesized from Section 5 prose. Revisit at Increment 4. |
| C3 | EgressLedgerEntry | `contracts/C3/EgressLedgerEntry/1.0.json` | Transcribed from the `append_ledger()` function body (Section 5.5) |
| C4 | CorpusManifest | `contracts/C4/CorpusManifest/1.0.json` | Transcribed verbatim (Section 3.4). `exclusions` key is required (may be empty) |
| C5 | AttributeRecord | `contracts/C5/AttributeRecord/1.0.json` | Transcribed verbatim (Section 3.3) - the pivot contract |
| C6 | ConceptCluster | `contracts/C6/ConceptCluster/1.0.json` | Full schema designed from the spec's abridged illustrative example (Section 3.5) |
| C7 | AlignmentRecord | `contracts/C7/AlignmentRecord/1.0.json` | Renamed from an earlier hand-written `Alignment` to match the spec's naming. `verdict=fit` requires a non-null `acordRef` (anti-hallucination guardrail, G1) via an `if`/`then` conditional |
| C8 | CanonicalCandidate | `contracts/C8/CanonicalCandidate/1.0.json` | Renamed from an earlier hand-written `Candidate` |
| C9 | CoverageReport | `contracts/C9/CoverageReport/1.0.json` | Transcribed from the `coverage()` function body (Section 9.8) |
| C9 | GapEntry | `contracts/C9/GapEntry/1.0.json` | **Interpreted, not verbatim spec** - only a one-line API reference exists (`GET /gaps -> {gaps: [GapEntry]}`), no field definition. Fully synthesized. Revisit at Increment 8. |
| C10 | MappingSpec | `contracts/C10/MappingSpec/1.0.json` | **Interpreted, not verbatim spec** - the spec gives an EBNF grammar for a YAML-like DSL (Section 10.2), not a JSON Schema; this is a translation into the parsed-document shape. `mappings[].oneOf(transform, disposition)` encodes invariant I5. Revisit at Increment 9. |
| C11 | RunManifest | `contracts/C11/RunManifest/1.0.json` | Transcribed from the Section 3.6 worked example. `state` is an open string, not a closed enum, since no exhaustive state list exists until the Increment 6 state machine is built |
| C11 | JournalEvent | `contracts/C11/JournalEvent/1.0.json` | Transcribed from the Section 3.6 worked example |

## Cross-artefact invariants (I1-I6)

JSON Schema validates a single document; these six invariants need more
than one document in hand at once, so they're enforced by
`contracts/validators.py`, not by schema alone:

| Invariant | Rule | Function |
|---|---|---|
| I1 | Every `AttributeRecord.evidenceRefs` entry resolves to an artefact in the run's `CorpusManifest` | `check_i1_evidence_resolvable` |
| I2 | Every `ConceptCluster` member references an `AttributeRecord` from the same run | `check_i2_cluster_members_same_run` |
| I3 | Every `CanonicalCandidate` traces through a `ConceptCluster` to a real `AttributeRecord` | `check_i3_candidate_traces_to_attribute` |
| I4 | A scored attribute contributes to `CoverageReport` only with both evidence and a named ratifying SME | `check_i4_coverage_scored_attributes_evidenced` |
| I5 | Every `MappingSpec` entry carries exactly one of `transform` or `disposition` | `check_i5_mapping_entries_have_disposition` |
| I6 | `EgressLedgerEntry.prevHash` forms an unbroken chain per region | `check_i6_ledger_chain_unbroken` |

**Important gap, documented in `contracts/validators.py`'s module
docstring**: some contracts use JSON Schema `if`/`then` or `oneOf`
conditionals (C7's fit/partial/misfit guardrails, C10's
transform-xor-disposition rule) that `jsonschema.Draft202012Validator`
enforces but the *generated Pydantic models do not enforce on their own*.
Constructing a generated model successfully is not proof a document
satisfies its schema - any code that writes or accepts C1-C11 documents
must run both validation paths.

## Known design gaps to close in later increments

- C2, C9.GapEntry, and C10 are synthesized/interpreted rather than
  spec-verbatim (see table above) - revisit once the increment that
  consumes each one (I4, I8, I9 respectively) is implemented for real.
- `RunManifest.state` will likely become a closed enum once Increment 6's
  state machine defines the full state list.
