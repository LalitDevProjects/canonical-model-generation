# parsers

Populated at Increment 3. Parsers to IR (the "flat AttributeRecord form",
per the spec's own glossary) - each produces `generated.C5.AttributeRecord`
instances directly, matching the spec's own worked golden-file test
(`parse_xsd(golden(...))`), not a separate intermediate structure.

- `type_normalisation.py` — the authoritative lookup table (Section 4.3):
  `from_openapi`/`from_xsd_qname`/`from_avro`, mapping each source
  system's type strings to the 11 normalised `DataType` values. "Unknown
  never silently defaults to string" is enforced structurally here; the
  companion "always raises a finding" half belongs to
  `algorithms/profiling.py`, in a separate pass.
- `record_builder.py` — shared identity/evidence construction
  (`attributeId`/`evidenceRefs`/`evidenceTier`/`inferred`) used by every
  parser, so the Increment 1-2 conventions apply in exactly one place.
- `openapi.py` — `parse_openapi`: real recursive walk of
  `components.schemas.*` plus path parameters.
- `xsd.py` — `parse_xsd`: all five idioms from Section 4.4 (xs:choice,
  substitution groups, attribute-vs-element normalisation, nillable vs.
  minOccurs, xs:extension flattening), via `lxml`. Exposes
  `_parse_xsd_tree`, shared with `wsdl.py`.
- `wsdl.py` — `parse_wsdl`: thin wrapper extracting the embedded
  `<xsd:schema>` and delegating entirely to `xsd.py` - WSDL is treated
  purely as an XSD-type carrier, per the spec's own confirmed scope.
- `avro.py` — `parse_avro`: deliberately thin, per the spec's own
  "corroborating evidence only in wave 1" framing. Uses the stdlib `json`
  module, not `fastavro` (a documented, confirmed deviation from the
  spec's tech-stack table - an `.avsc` file is itself JSON, and this
  increment only needs to walk its field structure).
- `router.py` — dispatches a fetched artefact to the right parser by
  `mediaType`, disambiguating `.xsd` vs `.wsdl` (which share
  `application/xml`) by root element tag.
- `code_inference.py` — stub. Out of scope: unscheduled in the spec's own
  9-increment build guide (Section 4.5's inference pipeline is never
  bound to any increment's acceptance test).

See `docs/increments.md` for what Increment 3 built and verified, and
`docs/contracts.md` for the `typeDetail` shape these parsers populate.
