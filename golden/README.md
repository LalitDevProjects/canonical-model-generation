# golden

The golden corpus (Section 16.2): "A curated, checked-in corpus of roughly
40 artefacts across the three regions, containing deliberately planted
difficulties... extended every time a real defect is found."

Built incrementally, not all at once - each increment adds only the
planted difficulty its own acceptance test needs:

- **Increment 2**: `git/claims-{us,uk,eu}/openapi.yaml` (uniform
  field shape across regions, deliberately - the synonym/homonym
  differences are Increment 7's job, not this one's) and
  `git/off-domain/cafeteria-menu.yaml` (a genuine, well-formed but
  off-domain artefact, since none of the spec's 11 named planted
  difficulties is a clean "excluded by relevance filtering" example - I2
  needed to add its own). `confluence/claims-uk-glossary.json` - a
  Confluence-fixture page whose content scores in the pass-1 "uncertain"
  band, exercising the third relevance-filter outcome.
- **Increment 3**: `xsd/uk/ClaimNotification.xsd` - the spec's
  own literal test path, realising all five XSD idioms (Section 4.4) in
  one document plus the planted untyped-date case
  (`notificationDate: xs:string`, fully builder-instantiated - the spec
  gives zero concrete detail for this planted case). `wsdl/uk/
  ClaimNotificationService.wsdl` wraps the same schema content, proving
  WSDL-as-XSD-carrier delegation. `avro/us/ClaimEvent.avsc`, deliberately
  thin per Avro's "corroborating evidence only" scope. New top-level
  buckets (`xsd/`, `wsdl/`, `avro/`), not under `git/`, since
  `tests/connectors/test_golden_corpus_e2e.py` (Increment 2) hard-asserts
  an exact artefact count against everything under `git/` - adding a file
  there would have silently broken an already-passing acceptance test.
- **Increment 4**: `gate/uk/claim-with-example.yaml` - the planted
  personal-data example, carrying the spec's own worked tokenise() input
  values ("A. Smith", "SW1A 1AA" - Section 5.3) as a `claimant` field's
  OpenAPI `example`. A new top-level bucket (`gate/`), same reasoning as
  Increment 3's `xsd/`/`wsdl`/`avro/` - adding it under `git/` would have
  broken `test_golden_corpus_e2e.py`'s exact artefact-count assertion.
  The licence-restricted-artefact case needs no new content fixture - it's
  an artefact-level metadata check, exercised via a
  `licence_disposition_by_system` override parameter (same pattern
  `evidence_tier_by_system` already uses); see
  `tests/gate/test_acceptance.py`.
- **Increment 5**: `substrate/graph_fixture.json` - the hand-authored
  deep-graph layer (Cluster/AcordConcept/Candidate/Decision/Release have
  zero real producers until Increments 7-9) needed to prove the
  four-hop lineage query for real, loaded via the exact same
  `graph.write_node`/`write_edge` functions production ingestion calls.
  Its seed attribute is a genuinely real one, parsed from
  `xsd/uk/ClaimNotification.xsd`. A new top-level bucket (`substrate/`),
  same reasoning as prior increments.
- **Increment 6**: `agents/scout/off_domain.json` (benign, off-domain
  Confluence-shaped page) and `agents/scout/injection.json` - the
  planted injection string, an embedded instruction override
  ("Ignore all previous instructions...") wrapped around genuinely
  off-domain content. Both are verified to land in pass-1's own
  "uncertain" band (score 0.63, between `pass1_drop` 0.20 and
  `pass1_keep` 0.65 - their space key deliberately contains a domain
  token, e.g. `CLAIMSHR`, so pass 1 can't resolve them on the URI alone),
  so they genuinely reach Repository Scout rather than being filtered
  out before the agent ever sees them. A new top-level bucket
  (`agents/`), same reasoning as prior increments.
- **Increment 8**: `coverage/{attributes,clusters,candidates,exclusions}.json`
  - hand-authored real C5/C6/C8/exclusion JSON (a new top-level bucket,
  same reasoning as every prior increment - clusters/candidates are
  themselves synthesized artefacts with no "raw" source format to parse
  them from, matching Increment 5's own `substrate/graph_fixture.json`
  precedent). Plants exactly the acceptance test's own scenario: a
  clean, 3-region, ratified `claimId` concept; a weight-5 `lossDate`
  concept with no candidate synthesised at all (the seeded unresolved
  mandatory attribute Gate 1 must block on); an unratified
  `reserveAmount` candidate (Gate 3); one corpus-level exclusion. See
  `tests/algorithms/test_coverage_acceptance.py`.
- **Increment 7**: `clustering/{us,uk,eu}/claim.yaml` - real, small
  OpenAPI fragments through the real `parsers/openapi.py` path (a new
  top-level bucket, same reasoning as prior increments - the existing
  `git/claims-{us,uk,eu}/openapi.yaml` all use uniform `lossDate` across
  regions and are hard-count-asserted by `test_golden_corpus_e2e.py`).
  The planted synonym triple (`lossDate`/US, `dateOfLoss`/UK,
  `dateSurvenance`/EU, sharing a parent shape and a declared date-pattern
  constraint) and the planted homonym (`Claim.metadata.claimDate` - UK:
  mandatory `dateTime`, "when the record was created"; EU: optional
  `string`, "a policy-administration reference date, unrelated to the
  claim event itself") were both empirically score-verified via a
  scratch script before being locked in - a real problem was caught this
  way: an early draft let the homonym's shared context spuriously
  cross-link it to the unrelated synonym triple, fixed by giving each
  its own parent shape and constraint. See
  `tests/algorithms/test_clustering_acceptance.py`.
- **Increment 9**: `mapping/region_attributes.json` (7 real C5
  AttributeRecord entries) + `mapping/uk-claims-v3.mapping.json`
  (Appendix C's own worked mapping specification, transcribed as real
  C10 JSON) - a new top-level bucket, same reasoning as every prior
  increment. One entry is deliberately adapted from Appendix C's own
  text: `coveragesInForce[].limit` is flattened to a non-array path
  (`coverageLimit`/`Cover.LimitAmount`), since
  `mapping/interpreter.py`'s own `read_path`/`write_path` do not resolve
  `[]` array segments (a documented PoC scope boundary, not a defect -
  see that module's own docstring). Everywhere else the fixture is
  textually faithful to Appendix C, including its one declared
  precision loss on `ClaimHeader.LossDate`. Reuses
  `golden/coverage/{candidates,clusters}.json` (Increment 8's own golden
  data) directly for the emission side of the acceptance test, rather
  than duplicating a parallel candidate/cluster fixture set. See
  `tests/emit/test_i9_acceptance.py`.
- Not yet claimed by any increment's acceptance test: granularity
  mismatch, enumeration divergence, obligation inversion,
  undocumented/code-only service.

`git/` is copied into a real temporary git repository by
`tests/connectors/conftest.py`'s `golden_git_repo` fixture (real `git
init`+commit, real commit SHAs) rather than being a git repository itself
- nesting a real `.git` inside this repository would need submodule
handling for no real benefit over a hermetic per-test temp repo.
