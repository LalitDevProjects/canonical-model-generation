# Increment Status

Tracks progress against the PoC Build Guide's nine increments
(`TECHNICAL_SPECIFICATION.txt`, Section 17.2). Sequencing rules (Section
17.3): contracts before code; the gate before any real evidence moves;
deterministic components before probabilistic ones; coverage before
emission.

| # | Increment | Status | Acceptance test (spec's wording) |
|---|---|---|---|
| I1 | Skeleton and contracts | **Complete** | CI is green; every contract has a positive and a negative fixture; model generation is reproducible from schema |
| I2 | Connectors and manifest | **Complete** | A run over the golden corpus produces a sealed manifest whose `corpusHash` is stable across repeats, with every excluded artefact carrying a reason |
| I3 | Parsers to IR | Not started | Golden-file tests pass byte-exact; the planted `xsd:choice` survives as variants; the untyped date raises `type-suspicion` |
| I4 | Gate and ledger | Not started | The planted personal-data example is masked; the licence-restricted artefact is blocked and appears in `exclusions`; the ledger chain verifies |
| I5 | Substrate and retrieval | Not started | Retrieval is deterministic across repeats; the four-hop lineage query returns the expected path |
| I6 | Agent runtime | Not started | A denied tool call is journalled and refused; a schema violation retries then escalates; the planted injection string changes nothing |
| I7 | Clustering and conflicts | Not started | Planted synonyms cluster; the planted homonym does not merge; evaluation harness meets the Semantic Resolver thresholds |
| I8 | Synthesis and coverage | Not started | Coverage is computed with a published denominator; Gate 1 blocks correctly on a seeded unresolved mandatory attribute |
| I9 | Emission and workshop pack | Not started | Emitted schemas validate; every round-trip test passes or its loss is declared; the pack is complete enough to run a real session from |

## I1 - what was built

- Repository restructured to the spec's mandated layout (Section 17.4);
  the prior implementation moved to `archive/legacy_src/` rather than
  extended in place, since it diverged fundamentally from the spec (see
  `README.md`'s Build Status section)
- All eleven contracts (thirteen schema files, C9 and C11 each split into
  two documents) as JSON Schema 2020-12 under `contracts/`, with shared
  `$defs` in `contracts/common/defs.json` - see `docs/contracts.md`
- Pydantic v2 models generated via `datamodel-code-generator`
  (`scripts/generate_models.py`), reproducible: running the script twice
  against an unchanged `contracts/` tree produces byte-identical output
- `contracts/validators.py`: the six cross-artefact invariants (I1-I6)
  that JSON Schema alone can't express
- 46 per-contract fixtures (positive + meaningfully-invalid negative) and
  12 multi-record invariant bundle fixtures, all exercised by parametrized
  pytest modules under `tests/contracts/`
- `config/settings.py` + `config/platform.yaml`: layered configuration
  with the five spec-named feature flags and a hard-locked
  `egress.fail_mode`
- `mypy --strict` clean across `generated/`, `contracts/`, `config/`,
  `tests/`; 100% coverage on the modules in scope (target was 85%)
- `.github/workflows/ci.yml`: install, regenerate-and-diff (fails on
  `generated/` drift), typecheck, test+coverage
- `infra/docker-compose.yml`: local Postgres + pgvector, for later
  increments (not used by I1's own runtime, which has none)

## I2 - what was built

- `connectors/base.py`: the `Connector` ABC (`discover`/`fetch`/`health`)
  and its supporting dataclasses, filling in shapes the spec's pseudocode
  leaves undefined
- `connectors/git_connector.py`: `GitConnector`, real `git` CLI plumbing
  (`rev-parse`, `ls-tree`, `show`) against a local repo - real commit SHAs,
  tested against a hermetic temp repository, not a mock
- `connectors/confluence_connector.py`: `ConfluenceConnector`, reads local
  JSON fixtures shaped like a Confluence Cloud REST response - a
  documented stand-in, since no real Confluence instance exists
- `connectors/relevance.py`: `filter_relevance`, the spec's two-pass
  relevance filter. Pass 1 (deterministic scoring) fully implemented; pass
  2's Repository Scout agent doesn't exist until Increment 6, so the
  `uncertain` band defaults to **kept, with a logged warning**, via a
  swappable `scout_classifier` parameter Increment 6 will replace
- `connectors/manifest.py`: `assemble_corpus_manifest` (discover → filter
  → fetch only what's kept → hash → seal) and `compute_corpus_hash` (sha256
  over canonical-JSON, sorted content hashes - the exact construction the
  schema doesn't specify, reusing the ledger's own `canonical_json`
  precedent)
- `pipeline/run_store.py`: `RunStore`, minimal local persistence for the
  sealed C4 manifest at `run-store/{runId}/S1/corpus_manifest.json`
- `golden/`: a small real Claims-domain corpus (3 regional OpenAPI files,
  1 off-domain artefact, 1 Confluence-fixture page) exercising all three
  pass-1 outcomes (keep/drop/uncertain) - see `golden/README.md` for what's
  deferred to later increments
- `config/settings.py` + `platform.yaml`: `RelevanceConfig`
  (`pass1_keep`/`pass1_drop`/`domain_tokens` transcribed verbatim from
  Section 15.1; `pass1_weights`/`contract_media_types` are documented
  builder defaults) and `StorageConfig.run_store_path`
- 138 tests passing (up from 87 at I1), `mypy --strict` clean, 99.9%
  coverage on `generated/contracts/config/connectors/pipeline` (target 85%)
- The literal acceptance test (`tests/connectors/test_golden_corpus_e2e.py`)
  runs real connectors over the real golden corpus and proves `corpusHash`
  stability across two independent invocations and that the one excluded
  artefact carries a reason - directly, not by paraphrase

**Confirmed decision**: the pass-1 "uncertain" relevance band defaults to
**kept** (not excluded) until Increment 6's Repository Scout exists. See
`connectors/relevance.py`'s `default_uncertain_policy` docstring for the
full reasoning (the C4 schema's own words: "a silently excluded source is
indistinguishable from an absent one").

## Decisions locked in for the rebuild (apply across all increments unless revisited)

- LLM/model gateway: provider-abstracted (tier-based, no concrete model
  names anywhere), backed by a mock provider until Increment 6
- ACORD Reference Architecture data: not licensed/available: build
  Increment 8's alignment against the spec's degraded mode (Section 19.2)
  unless this changes
- Storage: local Postgres + pgvector via Docker Compose is the intended
  target once a real store is needed (Increment 5 onward)
- Golden corpus: synthetic, built per the spec's own recommendation, not
  real regional data
- Placeholder domain `canonicalmodel.internal` in schema `$id`s
- Pacing: one increment at a time, checkpointed with the user before the next starts
