# emit

Populated at Increment 9. Section 11's artefact emission: real, validating
JSON Schema documents, an OpenAPI projection, a JSON-LD logical model
export, and a release manifest - assembled into a concrete workshop pack
(`workshop_pack.py`), the S8 "Emission" barrier stage's own named
deliverable.

- `common_schemas.py` - the six static `common/` type documents (Party,
  PostalAddress, MonetaryAmount, ContactPoint, DocumentRef, Identifier -
  Section 11.1's worked layout). `MonetaryAmount`/`Identifier` are shaped
  to match exactly what `mapping/transforms.py`'s own
  `toMonetaryAmount`/`toIdentifier` produce at runtime.
- `schema.py` - `build_entity_schemas()`/`build_extension_schemas()`:
  one schema per entity from real C8 CanonicalCandidate data, core
  attributes only inlined (`additionalProperties: false` everywhere,
  extension points as `$ref`-only per Section 11.1's own rule). C8's
  `dataType` field has no room for richer canonical type names
  ("MonetaryAmount", "Identifier") - the same documented gap
  `agents/canonical_synthesiser.py`'s own G2 guardrail already works
  around - so a candidate holding one of those values still emits as a
  plain `object`. `serialise()` is the determinism primitive every
  emitter in this package reuses: sorted keys, two-space indent, LF
  endings, bytes (never a text-mode file handle, so no platform can
  substitute CRLF).
- `openapi.py` - `build_openapi_projection()`: `components.schemas` is
  bare `$ref`s into the entity schemas above, `paths: {}` (Section 12's
  HTTP service APIs are out of this 9-increment PoC's scope). "The
  OpenAPI document references the component schemas; it adds no type
  definitions of its own."
- `logical_model.py` - `build_logical_model()` (Section 11.3's JSON-LD
  shape). `realisedBy`/`derivedFrom` carry real lineage strings, built
  from caller-supplied evidence/alignment maps rather than a live
  substrate query - the recursive-CTE lineage query itself stays proven
  exactly where Increment 5 proved it (`pytest.mark.db`); this module
  only has to produce documents consistent with what that query would
  return. `ratifiedBy.session` uses `ratification.decidedAt` - no
  session-naming field exists anywhere in this repo's data model, the
  same class of honest substitution as `algorithms/coverage.py`'s own
  `sole_region()`.
- `release.py` - `ReleaseManifest`/`build_release_manifest()`, validated
  against `schemas/release_manifest.schema.json`. **Not** a 12th
  C-numbered contract (Appendix A's contract index closes at C11) - see
  `docs/contracts.md`'s "Known design gaps" section for why this is a
  real, hand-written schema living under `emit/` rather than
  `contracts/`. `signature` is a caller-supplied PoC placeholder, the
  same status `config/settings.py::EgressConfig.ledger_signing_key`
  already carries for its own key material - no real signing
  infrastructure exists in this repo.
- `workshop_pack.py` - `assemble_pack()`: a real directory of files (not
  a live service) plus one indexing `WorkshopPackManifest` (sha256 +
  description per file). Writes every emitted schema, the OpenAPI
  projection, the logical model, every compiled mapping spec (both a
  JSON source-of-truth and a human-readable YAML rendering, plus its own
  value maps), the real coverage report and gap register
  (Increment 8), the release manifest, and a real, labelled
  `acord-alignment.md` manual-completion section - Section 19.2's own
  degraded-mode language ("the workshop pack carries an ACORD alignment
  section for SMEs to complete manually"), since ACORD Reference
  Architecture data has been unavailable in this repo since Increment 1.

See `mapping/README.md` for the DSL/compiler/interpreter this package's
mapping-spec emission depends on, and `docs/increments.md` for Increment
9's full build record and the acceptance test proving all three of its
clauses together.
