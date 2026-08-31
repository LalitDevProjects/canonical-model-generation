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

`contracts/common/defs.json`'s `exclusionReason` enum gained
`"policy-blocked"` at Increment 4: `block-unlicensed` (Section 5.4) maps
to the more specific pre-existing `licence-blocked`; every other gate
policy rejection (e.g. `block-personal`) maps to `policy-blocked`.
Regenerated and verified byte-reproducible before any gate code was
written, same rigor as every other contract change in this repo.

`contracts/C11/JournalEvent/1.0.json`'s `kind` enum gained
`"tool.denied"` at Increment 6 - not just a missing field, the enum had
no way to represent a denied tool call at all. Section 7.2: "the attempt
is journalled as a tool.denied event"; Section 13.3: "tool.denied events
and V4 guardrail violations are monitored. A spike in either is treated
as a potential injection." Two new optional properties came with it:
`tool` (the tool name requested) and `detail` (free text - the denial
reason for `tool.denied`, or which guardrail/violation fired for
`validation.failure`). Both optional, so every pre-Increment-6 journal
event stays valid. Regenerated and verified byte-reproducible before any
agent-runtime code was written.

## Contracts

| ID | Name | Schema path | Status |
|----|------|-------------|--------|
| C1 | SourceArtefact | `contracts/C1/SourceArtefact/1.0.json` | Extracted from C4's embedded artefact object into its own `$ref`-able schema (spec embeds it inline; this is a structural choice for single-source-of-truth generation, not a spec requirement) |
| C2 | SanitisationRecord | `contracts/C2/SanitisationRecord/1.0.json` | **Interpreted, not verbatim spec** - no JSON Schema or exhaustive field list exists in the spec; synthesized from Section 5 prose. Genuinely populated by the gate as of Increment 4 (`gate/gate.py::classify_and_redact`), superseding the Increment 2 placeholder; the schema's shape itself is unchanged |
| C3 | EgressLedgerEntry | `contracts/C3/EgressLedgerEntry/1.0.json` | Transcribed from the `append_ledger()` function body (Section 5.5) |
| C4 | CorpusManifest | `contracts/C4/CorpusManifest/1.0.json` | Transcribed verbatim (Section 3.4). `exclusions` key is required (may be empty) |
| C5 | AttributeRecord | `contracts/C5/AttributeRecord/1.0.json` | Transcribed verbatim (Section 3.3) - the pivot contract. `typeDetail` tightened at Increment 3 (see table below) |
| C6 | ConceptCluster | `contracts/C6/ConceptCluster/1.0.json` | Full schema designed from the spec's abridged illustrative example (Section 3.5). Genuinely populated as of Increment 7 (`algorithms/clustering.py::build_cluster`, `agents/semantic_resolver.py`) - every field the real producers needed already existed; no schema change was required |
| C7 | AlignmentRecord | `contracts/C7/AlignmentRecord/1.0.json` | Renamed from an earlier hand-written `Alignment` to match the spec's naming. `verdict=fit` requires a non-null `acordRef` (anti-hallucination guardrail, G1) via an `if`/`then` conditional. `verdict` gained `"unassessed"` at Increment 8 (see below) |
| C8 | CanonicalCandidate | `contracts/C8/CanonicalCandidate/1.0.json` | Renamed from an earlier hand-written `Candidate`. `vendorOnly` (optional, default `false`) added at Increment 8 (see below) |
| C9 | CoverageReport | `contracts/C9/CoverageReport/1.0.json` | Transcribed from the `coverage()` function body (Section 9.8). Genuinely populated as of Increment 8 (`algorithms/coverage.py::coverage`) - every field the real producer needed already existed; no schema change was required |
| C9 | GapEntry | `contracts/C9/GapEntry/1.0.json` | **Interpreted, not verbatim spec** - only a one-line API reference exists (`GET /gaps -> {gaps: [GapEntry]}`), no field definition. Fully synthesized at Increment 1. Genuinely populated as of Increment 8 (`algorithms/coverage.py::gap_register`) - the existing shape (`conceptId` as "ConceptCluster or CanonicalCandidate reference," `reason` enum `unresolved`/`unevidenced`/`excluded`/`below-region-floor`) turned out to already be sufficient; no schema change was needed |
| C10 | MappingSpec | `contracts/C10/MappingSpec/1.0.json` | **Interpreted, not verbatim spec** - the spec gives an EBNF grammar for a YAML-like DSL (Section 10.2), not a JSON Schema; this is a translation into the parsed-document shape. `mappings[].oneOf(transform, disposition)` encodes invariant I5. Revisit at Increment 9. |
| C11 | RunManifest | `contracts/C11/RunManifest/1.0.json` | Transcribed from the Section 3.6 worked example. `state` is an open string, not a closed enum, since no exhaustive state list exists until the Increment 6 state machine is built |
| C11 | JournalEvent | `contracts/C11/JournalEvent/1.0.json` | Transcribed from the Section 3.6 worked example. `kind` gained `"tool.denied"` at Increment 6, plus optional `tool`/`detail` fields (see below) |

## Cross-artefact invariants (I1-I6)

JSON Schema validates a single document; these six invariants need more
than one document in hand at once, so they're enforced by
`contracts/validators.py`, not by schema alone:

| Invariant | Rule | Function |
|---|---|---|
| I1 | Every `AttributeRecord.evidenceRefs` entry resolves to an artefact in the run's `CorpusManifest` | `check_i1_evidence_resolvable` |
| I2 | Every `ConceptCluster` member references an `AttributeRecord` from the same run | `check_i2_cluster_members_same_run` (genuinely exercised as of Increment 7 - Increment 6's own V5 dispatch onto it had no ConceptCluster producer yet) |
| I3 | Every `CanonicalCandidate` traces through a `ConceptCluster` to a real `AttributeRecord` | `check_i3_candidate_traces_to_attribute` (genuinely exercised as of Increment 8 - `agents/canonical_synthesiser.py`'s own `validate_semantics` reuses it directly) |
| I4 | A scored attribute contributes to `CoverageReport` only with both evidence and a named ratifying SME | `check_i4_coverage_scored_attributes_evidenced` (pre-built at Increment 1 anticipating exactly this shape; genuinely exercised as of Increment 8 - `algorithms/coverage.py`'s own `_classify()` implements the same rule inline for real-time computation, cross-checked against this function in `tests/algorithms/test_coverage_acceptance.py`) |
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

## `unwrap_ref` (promoted to public at Increment 7)

`contracts/validators.py::unwrap_ref` (renamed from `_unwrap`) unwraps
the RootModel wrapper `datamodel-code-generator` leaves on `$ref`-typed
scalar fields used *inside* a list (e.g. `evidenceRefs: list[EvidenceRef]`)
or an `anyOf` - a bare top-level `$ref` property collapses to a plain
constrained `str`, but the same `$def` used in those two positions stays
a `RootModel[str]` instance whose `str()` is `"root='...'"`, not the
underlying value. `algorithms/clustering.py::build_cluster` needed this
directly (assembling a `ConceptCluster`'s own `evidenceRefs` from its
members' real `AttributeRecord.evidenceRefs`), the same class of
cross-module reuse as `artefact_id_from_evref`'s own Increment 6
promotion.

## C5 `typeDetail` (tightened at Increment 3)

`typeDetail` was fully free-form at Increment 1; Increment 3's parsers
(`parsers/type_normalisation.py`, `parsers/xsd.py`) populate a locked-down
shape (`additionalProperties: false`) covering every key the spec names:

| Key | Type | Populated by |
|---|---|---|
| `bits` | integer | Integer bit width (xs:int/xs:long, OpenAPI int32/int64, Avro int/long) |
| `offsetRequired` | boolean | dateTime: whether the source format mandates a UTC offset |
| `refTarget` | string | A `$ref`/`xs:IDREF` target |
| `choiceGroup` | string | Section 4.4: shared identifier for every branch of one `xs:choice` group |
| `substitutionHead` | boolean | Section 4.4: true on an XSD substitution group's head element |
| `substitutionOf` | string | Section 4.4: a substitution-group member's reference to the head's `attributeId` - the field name is a builder decision (not named in the spec), by analogy with `refTarget` |
| `explicitNull` | boolean | Section 4.4: XSD `nillable="true"` - MUST NOT be conflated with `cardinality`'s `0..1` (`minOccurs="0"`) |
| `inheritedFrom` | string | Section 4.4: `xs:extension` flattening - marks a member inherited from a base type |

## The concept graph's node types are not contracts (Increment 5)

Section 6.3 defines seven concept-graph node types (`Artefact`,
`Attribute`, `Cluster`, `AcordConcept`, `Candidate`, `Release`,
`Decision`) and seven edge types. Four of the node types
(`Artefact`/`Attribute`/`Cluster`/`Candidate`) are populated *from* real
C1/C5/C6/C8 records - their graph `node_id` is literally that contract's
own `artefactId`/`attributeId`/`clusterId`/`candidateId`. The other three
(`AcordConcept`/`Release`/`Decision`) have **no C-numbered contract
anywhere** - Section 6.3 introduces their field lists fresh, and
`contracts/` stops at C11. `substrate/graph.py` models their properties
as plain frozen dataclasses (`AcordConceptProps`/`ReleaseProps`/
`DecisionProps`), the same status as `algorithms/profiling.py`'s
`Finding`/`ProfiledAttribute` - a builder decision, not new JSON Schema
contracts, since nothing in this repo needs to validate them against a
schema independently of the graph write path itself.

## Known design gaps to close in later increments

- C9.GapEntry and C10 are synthesized/interpreted rather than
  spec-verbatim (see table above) - revisit once the increment that
  consumes each one (I8, I9 respectively) is implemented for real. C2 was
  in the same position until Increment 4, which implemented the gate that
  actually populates it.
- `RunManifest.state` will likely become a closed enum once Increment 6's
  state machine defines the full state list.
