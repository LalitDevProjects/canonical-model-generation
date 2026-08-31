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
| I3 | Parsers to IR | **Complete** | Golden-file tests pass byte-exact; the planted `xsd:choice` survives as variants; the untyped date raises `type-suspicion` |
| I4 | Gate and ledger | **Complete** | The planted personal-data example is masked; the licence-restricted artefact is blocked and appears in `exclusions`; the ledger chain verifies |
| I5 | Substrate and retrieval | **Complete** | Retrieval is deterministic across repeats; the four-hop lineage query returns the expected path |
| I6 | Agent runtime | **Complete** | A denied tool call is journalled and refused; a schema violation retries then escalates; the planted injection string changes nothing |
| I7 | Clustering and conflicts | **Complete** | Planted synonyms cluster; the planted homonym does not merge; evaluation harness meets the Semantic Resolver thresholds |
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

## I3 - what was built

- `contracts/C5/AttributeRecord/1.0.json`'s `typeDetail` tightened from
  fully free-form to a locked-down 8-field object (see `docs/contracts.md`)
  - regenerated and verified byte-reproducible before any parser code
    was written, matching Increment 1's own rigor for contract changes
- `parsers/type_normalisation.py`: the authoritative type-normalisation
  lookup (Section 4.3), enforced structurally (never a conditional):
  "unknown never silently defaults to string" and "monetary values never
  normalise to a float" are both properties of the lookup table's own
  construction, not runtime checks
- `algorithms/profiling.py`: `profile()` (Section 9.1), landed ahead of
  the rest of `algorithms/` (Increments 7-8) since I3's own acceptance
  test needs it directly - same precedent as I2's `pipeline/run_store.py`
- `parsers/openapi.py`, `parsers/xsd.py` (all five idioms from Section
  4.4), `parsers/wsdl.py` (delegates to `xsd.py`), `parsers/avro.py`
  (deliberately thin, stdlib `json` only - a confirmed, documented
  deviation from the spec's `fastavro` tech-stack row), `parsers/router.py`
- `golden/xsd/uk/ClaimNotification.xsd`: the spec's own literal test
  fixture path, realising all five XSD idioms plus the untyped-date
  planted case in one document; `golden/wsdl/` and `golden/avro/`
  fixtures alongside it
- 236 tests passing (up from 138 at I2), `mypy --strict` clean, 99.78%
  coverage on the modules in scope (target 85%)
- The three acceptance-test clauses each map to a literal, named test:
  `tests/parsers/test_xsd.py::test_xsd_choice_survives_as_variants`
  (reproduced as close to the spec's own worked test as real code
  allows), and `test_untyped_date_raises_type_suspicion` (parses the real
  planted fixture, then profiles it in a wholly separate pass - proving
  the parser/profiler separation structurally, not by paraphrase)

**Confirmed decision**: the Avro parser uses the stdlib `json` module,
not `fastavro` - deliberate, documented deviation from the spec's own
tech-stack table, since I3 only needs to walk an `.avsc` file's field
structure (itself plain JSON), not validate real data records against it
(fastavro's actual strength, and out of scope for Avro's confirmed
"corroborating evidence only in wave 1" role).

**Confirmed out of scope**: Section 4.5 code contract inference -
unscheduled in the spec's own 9-increment build guide (verified against
every increment's acceptance test); `parsers/code_inference.py` is a
documented stub.

## I4 - what was built

- `contracts/common/defs.json`: `exclusionReason` gained `"policy-blocked"`
  (`block-unlicensed` maps to the more specific `licence-blocked`; every
  other policy rejection maps to this) - regenerated and verified
  byte-reproducible before any gate code was written, same rigor as I1/I3's
  own contract changes
- `config/settings.py` + `platform.yaml`: `EgressConfig` gained
  `lawful_basis`, `ledger_signing_key` and `tokenisation_keys`
  (per-region, 64-hex-char PoC placeholders, fail-closed on malformed hex);
  `policy_version` bumped to match `gate/policy.yaml`'s own version
- **Resolved a real inconsistency in the spec's own two verdict
  mechanisms** (Section 5.1's ladder `block > mask > allow` vs. Section
  5.4's policy YAML, which never produces `mask` even though the
  acceptance test requires one): a two-tier model, where the ladder
  verdict is the final `C2`/`C3` verdict for anything the policy admits,
  and the policy verdict is a separate admit/reject gate that forces
  `block` when it rejects. See `gate/gate.py`'s module docstring for the
  full reasoning.
- `gate/policy.py` + `gate/policy.yaml`: `evaluate_policy`, transcribed
  from Section 5.4. Evaluates every rule (not first-match-wins by list
  order) so a matching block rule always wins over a matching allow rule -
  a real bug (`allow-structural` listed before `block-unlicensed`) caught
  by testing the function directly, not inferred from the prose
- `gate/structure.py` + `gate/detectors.py`: the L0-L4 classification
  ladder (L5 is a direct licence lookup, not a content detector - see
  `connectors/manifest.py`). L2 entity recognition is a lightweight,
  stdlib-only Title-Case heuristic (a confirmed decision, not spaCy) -
  provisional and documented as such; it only ever produces `mask`, never
  `block`, so over-triggering fails safe
- `gate/tokenisation.py`: `tokenise()` exactly per the spec's own Section
  5.3 pseudocode (HMAC-SHA256, label-prefixed); `redact()`, a deterministic
  substring replace-all over the original raw bytes (not a re-serialized
  structure, to avoid gratuitous formatting drift on untouched artefacts)
- `gate/ledger.py` + `gate/evidence_store.py`: `append_ledger_entry()`
  exactly per Section 5.5's `append_ledger()` pseudocode, and a minimal
  content-addressed evidence-store writer (`evidence-store/artefacts/{sha256[0:2]}/{sha256}`)
  - both a confirmed Increment 4 scope call, not deferred to I5
- `contracts/validators.py`: `check_i6_ledger_chain_unbroken` extended to
  recompute each entry's own `hash` from its body (catching tampering, not
  just a broken `prevHash` link) and verify `signature` when a signing key
  is supplied - "the ledger chain verifies" is read as covering entry
  integrity, not merely linkage
- `connectors/manifest.py`: the Increment 2 placeholder sanitisation
  (unconditional `verdict=allow`) is gone; every kept artefact now runs
  through the real gate (`gate.gate.classify_and_redact`). `contentHash`
  is now computed over gated (possibly redacted) content, not raw fetched
  bytes - mask-then-hash. A deliberate breaking signature change
  (`egress_cfg`/`policy`/`feature_flags`/`ledger_store`/`evidence_store`
  are now required parameters); `tests/connectors/test_golden_corpus_e2e.py`
  still passes with the same assertions (artefact count, exclusion count/
  reason, hash stability across repeats) - verified against real
  golden-corpus bytes, not assumed
- `golden/gate/uk/claim-with-example.yaml`: the planted personal-data
  example, using the spec's own worked `tokenise()` input values
  ("A. Smith", "SW1A 1AA")
- 345 tests passing (up from 236 at I3), `mypy --strict` clean, 99.6%
  coverage on the modules in scope (target 85%)
- The three acceptance-test clauses each map to a literal test:
  `tests/gate/test_acceptance.py::TestPlantedPersonalDataExampleIsMasked`
  (real fixture, `verdict=mask`, raw values absent / tokens present in the
  redacted output), `TestLicenceRestrictedArtefactIsBlockedAndExcluded`
  (end-to-end through `assemble_corpus_manifest`, absent from `artefacts`,
  present in `exclusions` with `reason="licence-blocked"`), and
  `tests/gate/test_ledger.py::test_a_freshly_read_back_chain_still_verifies_via_check_i6`
  / `test_check_i6_detects_a_corrupted_entry_after_a_round_trip` (a clean
  chain verifies; a deliberately corrupted one is caught)

**Confirmed decisions**: L2 NER is a lightweight stdlib heuristic, not
spaCy (see `gate/detectors.py`); the evidence store is a minimal writer
built now, not deferred to I5.

## I5 - what was built

- **Real Postgres + pgvector, not a local hermetic store** - a
  deliberate, user-confirmed decision to wire up the infrastructure
  `infra/docker-compose.yml` was built at Increment 1 specifically to
  anticipate, rather than defer it further. `psycopg[binary]` is the new
  dependency (no `pgvector` PyPI adapter - a 5-line hand-rolled vector
  literal formatter avoids an extra `numpy` dependency for a PoC).
- `substrate/schema.sql` + `substrate/db.py`: `nodes`/`edges` as a
  generic property graph (not one table per Section 6.3 node/edge type -
  see the schema's own docstring), `chunks`/`attribute_embeddings` with
  pgvector columns. Idempotent `CREATE TABLE IF NOT EXISTS` throughout,
  no migration tool - Section 6's own framing is that this data is
  "derived; may be dropped and reconstructed from the evidence store."
- `substrate/chunking.py`: one chunker per Section 6.2 artefact kind
  (OpenAPI/JSON Schema, XSD, WSDL, Confluence), tested against every
  relevant *real* golden fixture, not synthetic strings alone. Avro is
  absent from the spec's own table - `chunk_avro`'s "one chunk per named
  record/enum/fixed" is a documented builder default. Source code and
  the ACORD reference pack chunkers are not implemented - confirmed out
  of scope, same status as `parsers/code_inference.py`.
- `substrate/embedding.py`: `mock_embed()`, a deterministic, non-semantic
  placeholder for Increment 6's real model gateway (the Increment 1
  lock-in below already required this - Increment 5 cannot call a real
  embedding API).
- `substrate/graph.py`: idempotent node/edge writes plus `lineage()`, a
  bidirectional recursive CTE answering the spec's own worked query in
  one statement. `AcordConcept`/`Release`/`Decision` have no C-numbered
  contract anywhere (Section 6.3 introduces them fresh) - modelled as
  plain frozen dataclasses, the same status as
  `algorithms/profiling.py`'s `Finding`, not new JSON Schema contracts.
- `substrate/search.py`: hand-written BM25 (a confirmed decision - no
  `rank_bm25` dependency) and reciprocal-rank fusion, with
  `(score, chunk_hash)` as the literal, tested tie-break that makes
  `search()`'s ordering genuinely deterministic, not just usually so.
- `substrate/ingest.py`: the first real wiring of `parsers/router.py`
  (built at Increment 3, never previously run against a real pipeline)
  against admitted artefacts, reading their REDACTED content from the
  evidence store - never raw connector bytes, since the gate already
  redacted this content once at Increment 4. Gracefully skips attribute
  extraction (while still chunking) for artefact kinds with no
  registered parser, e.g. Confluence - a real gap caught during planning,
  not discovered by a failing test.
- `pipeline/run_store.py` gained `write_attributes`/`read_attributes`
  (`run-store/{runId}/S3/attributes/{region}.jsonl`, the storage
  layout's literal path) and `append_journal_event`/`next_journal_seq`.
- `substrate/api.py`: `SubstrateApi`, Section 6.4's five methods
  verbatim, against this repo's real generated contracts
  (`get_attribute`/`neighbours` return `generated.C5.AttributeRecord`
  directly). `acord_lookup` always returns an empty list and
  unconditionally journals the call - ACORD data is unlicensed in this
  repo regardless of the feature flag, consistent with Section 19.2's
  degraded mode.
- `golden/substrate/graph_fixture.json`: the hand-authored deep-graph
  layer (Cluster/AcordConcept/Candidate/Decision/Release have zero real
  producers until Increments 7-9) needed to prove the four-hop lineage
  query for real, loaded via the exact same `graph.write_node`/
  `write_edge` functions production ingestion calls - not a parallel
  test-only writer. Its seed attribute is a genuinely real one, parsed
  from `golden/xsd/uk/ClaimNotification.xsd`.
- 451 tests passing (up from 345 at I4), `mypy --strict` clean, ~99.7%
  coverage on the modules in scope (100% within `substrate/` itself);
  hermetic tests (the large majority) never touch a database, and
  `pytest.mark.db` tests skip cleanly with an actionable message when
  Postgres isn't reachable rather than failing the whole suite
- Both acceptance-test clauses map to a literal test in
  `tests/substrate/test_substrate_acceptance.py`:
  `TestRetrievalIsDeterministicAcrossRepeats` (two `search()` calls with
  identical arguments, byte-identical ordered chunk hashes and scores)
  and `TestFourHopLineageQueryReturnsTheExpectedPath` (every expected
  node type and edge type reachable from a seed `Candidate`, through the
  real `Attribute`/`Artefact` pair and the hand-authored deep layer)

**Confirmed decisions**: real Postgres + pgvector now, not deferred (a
genuine departure from every prior increment's local-store-only bias -
see the point above); BM25 is hand-written, no new dependency.

**Environment note, not a design decision**: this developer's machine
runs a separate, unrelated native PostgreSQL 18 Windows service on the
default port 5432 - `infra/docker-compose.yml` is remapped to host port
5433 to avoid the collision (see its own comment); `config/platform.yaml`
keeps the standard 5432 DSN, since CI and other machines have no such
conflict. Local test runs on this machine need
`CMGP_STORAGE__POSTGRES_DSN` set to override it - this env var is read
directly by `tests/substrate/db_fixture.py`, not by `load_settings()`
itself (which treats already-set YAML values as higher-precedence than
environment variables).

## I6 - what was built

- **Real Anthropic API provider, not a continued mock** - a deliberate,
  user-confirmed decision (against the recommendation to stay
  deterministic-mock even at this increment). `fast` tier resolves to
  `claude-haiku-4-5-20251001`, `high` to `claude-sonnet-5`
  (`config/platform.yaml`'s new `model_id` field per tier). The
  underlying provider call is injectable (`agents/model_gateway.py::ProviderFn`)
  - the agent framework's own logic (retry, escalation, tool
    authorisation, guardrails) is tested against a scripted fake
    throughout; a small `pytest.mark.llm`-marked suite exercises the
    real call and skips cleanly (same pattern as `pytest.mark.db`) since
    no `ANTHROPIC_API_KEY` was available this session - real end-to-end
    verification is the user's own follow-up once they have a key.
- **A real contract gap found and closed**: `contracts/C11/JournalEvent/1.0.json`'s
  `kind` enum had no `"tool.denied"` value at all (not just a missing
  field) - Section 7.2's "the attempt is journalled as a tool.denied
  event" had no way to be represented. Added `"tool.denied"` plus
  optional `tool`/`detail` fields, same rigor as Increment 4's
  `policy-blocked` addition - regenerated, verified byte-reproducible,
  confirmed every pre-existing journal test still passes unmodified.
- `agents/base.py`: the `Agent` ABC's literal ten-step `invoke()` path
  (Section 7.1), with Section 7.6's retry table as a real retry loop -
  schema failures retry twice with the validation error appended to the
  prompt, semantic failures retry once with the offending values named,
  guardrail violations get zero retries and escalate immediately. No
  S1-S8 orchestrator exists or is in scope this increment (Section
  8.3's own pseudocode is an AWS Step Functions definition this repo
  has no way to run, and no increment's acceptance test through I9
  needs a real one) - `route()` is an identity stub.
- `agents/validation.py`: the V1-V5 ladder. V1 (`jsonschema`), V2
  (reuses `contracts/validators.py`'s evref-parsing, promoted from
  `_artefact_id_from_evref` to public `artefact_id_from_evref`), V4
  (runs every guardrail to completion, same "ladder doesn't
  short-circuit" discipline as the L0-L4 sanitisation ladder). V3
  (provenance) is trivially satisfied at Increment 6 - neither agent
  invents enumeration values. V5 (cross-artefact I2-I5) dispatches
  directly onto the already-real invariant checks but is **genuinely
  unexercised** this increment: neither agent produces
  ConceptCluster/CanonicalCandidate/CoverageReport/MappingSpec data,
  none of which exist before Increments 7-9 - a real scope boundary.
- `agents/model_gateway.py`: `Budget`, transcribed from Section 7.6's
  own pseudocode with one real bug fixed (`self.stage_spend` was read
  in `check()` but never assigned in `__init__` - a real
  `defaultdict(int)` is what that line evidently intended), constructed
  **from** the already-real `generated.C11.RunManifest.Budget` field,
  not a new config section. Budget stage resolves from `WorkItem.stage`
  (Section 8.2), not a separately-maintained agent-to-stage map.
- `tools/`: the tool gateway (`ToolGateway`, authorisation + argument/
  result schema validation + `tool.call`/`tool.denied` journalling in
  one place) and the registry (`ToolDefinition`, matching the spec's
  one fully-worked example, `acord.lookup`, exactly). Real handlers for
  `artefact.write` (every agent's own write path, Section 7.1 step 9 -
  authorised for `"*"`, every agent, matching the table's "All
  families"), `spec.parse` (wraps `parsers/router.py::parse` - Schema
  Interpreter), and `substrate.query`/`substrate.neighbours`/`acord.lookup`
  (thin wrappers over the already-real `SubstrateApi`, unblocking
  Increment 7/8 agents even though neither of this increment's own
  agents calls them). `repo.search`/`repo.read`/`kb.search`/
  `catalogue.query` are registered (metadata only, per "every tool in
  7.2 is specified this way in `tools/`") but have no real handler yet
  - honestly deferred, not silently stubbed.
- `agents/repository_scout.py`: Repository Scout, explicitly deferred
  to this increment back at Increment 2
  (`connectors/relevance.py::default_uncertain_policy`'s own docstring:
  "no Repository Scout until Increment 6"). `make_repository_scout_classifier(ctx)`
  is a factory producing a closure matching `filter_relevance`'s exact
  `scout_classifier` signature - **zero changes to
  `connectors/relevance.py`**. Two guardrails: a verdict's own `reason`
  must not echo injected override language, and `in_domain=true`
  requires a real, non-whitespace reason - belt-and-braces code checks
  behind the real architectural controls (the prompt's `[INJECTION]`
  block; no consequential actions per Section 13.3).
- `agents/schema_interpreter.py` + `agents/deterministic.py`: Schema
  Interpreter, a thin `Agent`-ABC wrapper (`model_tier: n/a`, no prompt,
  no model call) around the already-real `parsers/router.py::parse`,
  reached through the `spec.parse` tool so the same authorisation/audit
  path a model-calling agent's tool use goes through also covers
  deterministic agents.
- `golden/agents/scout/`: `off_domain.json` (benign, off-domain) and
  `injection.json` (a planted instruction-override string embedded in
  otherwise off-domain content) - both real Confluence-shaped fixtures
  verified to land in pass-1's own "uncertain" band (score 0.63,
  between `pass1_drop` 0.20 and `pass1_keep` 0.65), so they genuinely
  reach the agent rather than being filtered out beforehand.
- **Eval harness deferred, not built**: Section 17.5's Definition of
  Done asks for "an evaluation-set result recorded" for any new
  agent/prompt, but Section 16.4's own threshold table names only
  Semantic Resolver/ACORD Aligner/Canonical Synthesiser/Adversarial
  Critic/Rule Extractor - nothing for Repository Scout or Schema
  Interpreter. Building `eval/` now would mean inventing thresholds
  with no spec grounding; documented as a deferred gap (same status as
  C9.GapEntry/C10), not required by this increment's own literal
  acceptance test.
- 558 tests passing (up from 451 at I5; 1 skipped - the real-call
  `pytest.mark.llm` test, pending an API key), `mypy --strict` clean
  across 142 source files, ~99.4% coverage overall (98%+ within
  `agents`/`tools` themselves - the only real gap is the live
  Anthropic HTTP call body, which cannot be exercised without a key).
- All three acceptance-test clauses map to literal tests in
  `tests/agents/test_agent_runtime_acceptance.py`:
  `TestADeniedToolCallIsJournalledAndRefused`,
  `TestASchemaViolationRetriesThenEscalates`, and
  `TestThePlantedInjectionStringChangesNothing` (both a direct
  classifier-level check and an end-to-end `filter_relevance` run).

## I7 - what was built

- **Confirmed architecture (user, this session): deterministic decides,
  agent adjudicates only the uncertain band.** `algorithms/clustering.py::run_clustering()`
  (blocking -> similarity -> graph connected-components -> homonym
  split -> conflict classification) is fully self-sufficient and alone
  satisfies the acceptance test's first two clauses, with zero LLM
  dependency - the Semantic Resolver agent is invoked only on
  review-band material (score in `[review_band_low, link_threshold)`)
  the deterministic pass can't confidently resolve. This mirrors
  exactly how Repository Scout (Increment 6) adjudicates
  `connectors/relevance.py`'s own "uncertain" middle band, and matches
  Section 17.3's "deterministic before probabilistic... if the agents
  disappoint, the platform still parses the estate."
- **A real, empirically-found problem with the spec's own weights,
  fixed and documented**: Section 9.3's literal `WEIGHTS`
  (`embedding: 0.30`) assumes a real semantic embedding model. This
  PoC's `substrate/embedding.py::mock_embed` (unchanged since Increment
  5) is a deterministic SHA256 hash with *no* semantic content by its
  own docstring's admission - under the spec's literal weights, two
  attributes identical in every other feature still cap out at score
  0.70, strictly below `LINK_THRESHOLD=0.72`, so *no* real pair could
  ever auto-link. `config/platform.yaml`'s `clustering.weights`
  discounts `embedding` to 0.05 (not 0.0) and redistributes the
  remainder across `lexical`/`type`/`constraints`/`context` in their
  original relative proportions - a documented PoC default, not a
  claim about the algorithm in general (see
  `config/settings.py::ClusteringConfig.weights`'s own field
  description for the full empirical reasoning). `TYPE_COMPATIBILITY`
  also gets one correction: same-datatype pairs resolve to 1.0 even
  when the table doesn't happen to enumerate that exact pair (the
  table's own "deliberately not equality" framing is about the
  *divergent* pairs it lists, not a claim that equality itself needs
  spelling out attribute by attribute) - the same class of fix as
  Increment 6's `Budget.stage_spend` bug.
- `algorithms/profiling.py` (Increment 3) is extended, not replaced:
  `canonical_tokens`/`head_noun` gain optional `abbreviations`/
  `lemmatise_fn`/`prefer` parameters, all defaulting to Increment 3's
  exact behaviour - `profile()` itself calls them with none of the new
  arguments, so `tests/algorithms/test_profiling.py` passes unmodified.
  `algorithms/blocking.py` is the only caller that supplies real
  arguments. The `prefer` parameter (last *preferred* token wins over
  strict positional-last) is what lets `dateOfLoss` head on `date` like
  `lossDate` does, using tokens already known to the system
  (`config.clustering.abbreviations`' own values plus profiling.py's
  existing `TEMPORAL_TOKENS`/`MONETARY_TOKENS`, both promoted to
  public) - no DB dependency needed for the golden synonym triple to
  co-block.
- `algorithms/blocking.py`: `build_blocks()` (by-head, by-type, and an
  optional DB-backed by-embedding key via `SubstrateApi.neighbours` -
  degrades to empty, not fatal, when `api`/`run_id` are omitted, which
  is what keeps the acceptance test hermetic), `dedupe_blocks()`
  (exact-duplicate collapse + deterministic attributeId-sorted
  truncation at `block_max_size`), `lemmatise()` (a documented
  "Porter-lite" suffix stripper, not a real lemmatiser).
- `algorithms/similarity.py`: `similarity()` against this repo's real
  `ProfiledAttribute`/`ClusteringConfig` shapes - `embeddings` is an
  explicit `dict[attributeId, vector]` parameter (from
  `compute_embeddings()`, reusing `substrate/ingest.py`'s now-public
  `attribute_embedding_text`), a documented deviation from the
  pseudocode's literal `a.embedding` attribute access, the same
  factory-for-signature-constraint status as Increment 6's
  `make_repository_scout_classifier`. `pattern_range_similarity()`
  implements real interval-overlap math for `range`/`length`
  constraints and exact-match for `pattern`/`format`/`crossField`/
  `custom` - including the non-obvious case that two *identical*
  open-ended ranges (both declaring only `minimum=0`, say) must score
  1.0, not 0.0, despite their union being infinite.
- `algorithms/graph.py`: hand-rolled BFS connected components - no new
  graph-library dependency (every dependency this repo has added so
  far was load-bearing/non-substitutable; PoC block sizes, `<=40`
  members per Section 8.6, make this trivial).
- `algorithms/conflict.py`: `HOMONYM_SIGNALS` (all five, including a
  fixed `divergent-parent-context` bug caught by its own test suite -
  two attributes that simply have *no recorded parentPath* were
  originally scoring as maximally divergent, the opposite of intended),
  `split_on_homonym_signals()`/`min_cut_until()` (a documented greedy
  lowest-edge-removal partition, explicitly not Stoer-Wagner), and all
  six Section 9.5 conflict classes (`classify_conflict()` for the four
  beyond synonym/homonym) since "conflict classification" is a named
  build-guide deliverable, not just what the acceptance test happens to
  probe. `contradiction_detected` (the one signal the spec ties to
  "critic-assessed, cached") is an honest permanent stub - the
  Adversarial Critic agent doesn't exist until Increment 8/9, matching
  `substrate/api.py::acord_lookup`'s own empty-list precedent for the
  same class of gap.
- `algorithms/clustering.py`: `run_clustering()` (the full pipeline),
  `build_cluster()` (deterministic, documented, provisional rules for
  fields the spec doesn't mandate - `clusterId` content-addressed from
  sorted member attributeIds; `role` = lowest-evidenceTier/most-central
  member as `core`; `proposedConcept` = shortest member `localName`;
  `confidence` = **min** of the cluster's pairwise edge scores,
  conservative and consistent with "a wrongly merged pair ships a
  defect"). `write_triage_export()` + `pipeline/run_store.py::TriageEntry`
  are the concrete "triage export" deliverable - one append-only JSONL
  sink (`run-store/{runId}/S4/triage.jsonl`) for both the deterministic
  review queue and the agent's own `AWAIT_TRIAGE` escalations - **not**
  the full Section 12.1 run-control API or Section 8.4 `AWAIT_*`
  checkpoint machinery, which stay out of scope this increment,
  matching Increment 6's own orchestrator-deferral precedent exactly.
- `prompts/semantic-resolver/2.3.0.md`: Section 7.5.1's blocks
  transcribed verbatim.
- `agents/validation.py` + `agents/base.py`: the one real, additive
  touch to already-tested Increment 6 framework code -
  `validate_schema()` gains an optional `registry: Registry | None`
  kwarg (default `None` preserves Increment 6's two agents' exact
  behaviour, whose schemas have no external `$ref`), and `Agent` gains
  a matching optional `schema_registry` class attribute. Needed because
  `contracts/C6/ConceptCluster/1.0.json` `$ref`s into
  `common/defs.json`, and Increment 6's `validate_schema` had no
  registry to resolve that with (fine for its own two agents, whose
  schemas had none).
- `agents/semantic_resolver.py`: `SemanticResolverAgent` - `output_schema`
  is the **real, unmodified** `contracts/C6/ConceptCluster/1.0.json`
  (loaded from disk, not hand-copied - a single source of truth), with
  a registry built once at import time via the same
  `Registry().with_resources()` pattern `tests/contracts/test_fixtures.py`
  already proved. Five real, code-checkable guardrails (G1-G5, Section
  7.5.1 verbatim) - G4 in particular operationalises "obligation
  conflicts MUST NOT be resolved here" as "a claimed
  `conflictClass=obligation` must correspond to a *genuine* obligation
  divergence among the real member records," catching an agent that
  invents one to dodge a merge decision. `validate_semantics()` checks
  for invented members (attributeIds not among the supplied anchor/
  candidates) and unresolvable `evidenceRefs` (against the input
  records' own already-I1-validated evidence - the same
  self-referential known-set trick Schema Interpreter already uses).
  `make_semantic_resolver_adjudicator(ctx)` is a factory - the same
  shape as `make_repository_scout_classifier` - grouping review-band
  pairs into their own connected components, one `WorkItem` per
  component, persisting `AWAIT_TRIAGE` escalations
  (`conflictClass=homonym` or `confidence<0.60`) to the same triage
  sink `run_clustering()` uses. The third escalation rule ("members
  span >3 source contracts -> adversarial-critic before S5") is
  honestly deferred, not acted on - that agent doesn't exist until
  Increment 8/9.
- `golden/clustering/{us,uk,eu}/claim.yaml`: real, small OpenAPI
  fragments through the real `parsers/openapi.py` path (a new
  top-level bucket, since `golden/git/claims-{us,uk,eu}/openapi.yaml`
  all already use uniform `lossDate` across regions and are
  hard-count-asserted by `test_golden_corpus_e2e.py`). The planted
  synonym triple (`lossDate`/US, `dateOfLoss`/UK, `dateSurvenance`/EU)
  and the planted homonym (`Claim.metadata.claimDate` - UK: mandatory
  `dateTime`, "when the record was created"; EU: optional `string`, "a
  policy-administration reference date, unrelated to the claim event
  itself") were both empirically score-verified via a scratch script
  before being locked in (a real, caught problem: an early fixture
  draft let the homonym's shared context/constraints spuriously
  cross-link it to the unrelated synonym triple, fixed by giving each
  its own parent shape and constraint) - `tests/algorithms/test_clustering_acceptance.py`
  is the literal acceptance test, running the real parse -> profile ->
  `run_clustering()` path with zero LLM and zero DB.
- `eval/` (deferred at Increment 6 - no thresholds existed for its two
  agents; real thresholds finally exist for Semantic Resolver) is
  built for real: `eval/thresholds.py` (Cluster F1 >= 0.88, homonym
  recall = 1.00 per Section 16.4), `eval/harness.py`
  (`evaluate()`/`score_one()`, gated on the **worst** of `n_repeats`
  runs per Section 16.4's own literal pseudocode, against an injectable
  `adjudicate_factory` rather than a hardcoded agent - the same DI
  convention as `gate/gate.py`/`substrate/ingest.py`/
  `agents/model_gateway.py`). Running 5 real Anthropic calls per eval
  case isn't reachable this session (no API key, the same still-current
  Increment 6 constraint) - the harness's own arithmetic (F1, homonym
  recall, worst-of-5 gating) is proven hermetically against a scripted
  adjudicator; one `pytest.mark.llm` test exercises the real
  `SemanticResolverAgent` end to end and skips cleanly.
- 704 tests passing (up from 558 at I6; 2 skipped - both real-model
  `pytest.mark.llm` tests, pending an API key), `mypy --strict` clean
  across 160 source files, ~99.5% coverage overall (100% within every
  module this increment touched or added - the only gap anywhere is
  Increment 6's own already-accepted live-Anthropic-call body).
- Acceptance-test clause mapping: "Planted synonyms cluster" and "the
  planted homonym does not merge" ->
  `tests/algorithms/test_clustering_acceptance.py` (zero LLM, zero DB
  - the deterministic pipeline alone). "evaluation harness meets the
  Semantic Resolver thresholds" -> `tests/eval/test_harness.py`'s
  worst-of-5 gating arithmetic, proven for real; live-threshold
  verification against a real model is the `pytest.mark.llm` test,
  honestly deferred pending an API key, the same posture as Increment
  6's own model-gateway acceptance clause.

**Confirmed decisions**: real Anthropic API provider (a genuine
departure from the "mock until Increment 6" framing, since Increment 6
is where that could change and the user chose to make it real); real
API calls stay opt-in-only in tests, mocked/injected by default;
Repository Scout + Schema Interpreter are the two agents, chosen for
having real, already-built supporting infrastructure (Increment 2's own
deferred callback; Increment 3's real parser) over inventing two
under-specified agents from scratch.

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
