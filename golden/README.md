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
- **Increment 3** (current): `xsd/uk/ClaimNotification.xsd` - the spec's
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
- **Increment 4** (not yet built): planted personal-data example,
  licence-restricted artefact.
- **Increment 6**: planted injection string.
- **Increment 7**: synonym triple (`lossDate`/`dateOfLoss`/`dateSurvenance`),
  homonym pair (`claimDate` meaning different things per region).
- Not yet claimed by any increment's acceptance test: granularity
  mismatch, enumeration divergence, obligation inversion,
  undocumented/code-only service.

`git/` is copied into a real temporary git repository by
`tests/connectors/conftest.py`'s `golden_git_repo` fixture (real `git
init`+commit, real commit SHAs) rather than being a git repository itself
- nesting a real `.git` inside this repository would need submodule
handling for no real benefit over a hermetic per-test temp repo.
