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
| I8 | Synthesis and coverage | **Complete** | Coverage is computed with a published denominator; Gate 1 blocks correctly on a seeded unresolved mandatory attribute |
| I9 | Emission and workshop pack | **Complete** | Emitted schemas validate; every round-trip test passes or its loss is declared; the pack is complete enough to run a real session from |

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

## I8 - what was built

- **Confirmed decision (user, this session): build the full, real ACORD
  Aligner agent class**, matching how Repository Scout/Schema Interpreter
  were built completely at Increment 6 even before every path could be
  exercised for real. ACORD Reference Architecture data has been
  permanently unavailable in this repo since Increment 1 (unlicensed;
  `substrate/api.py::acord_lookup` always returns `[]`) - the agent's
  own guardrail G4 ("if licence disposition != permitted, this agent
  MUST NOT run") means the real, always-exercised pipeline path in this
  repo is Section 19.2's deterministic degraded mode, not the agent
  itself. `agents/acord_aligner.py::align_or_degrade()` is the top-level
  dispatcher, enforcing G4 by never constructing a work item at all when
  disposition isn't "permitted" - there is nothing to guardrail-check in
  an invocation that never happens.
- **Two more genuine contract gaps found and fixed, same rigor as
  I4/I6/I7's own fixes**: `contracts/C7/AlignmentRecord/1.0.json`'s
  `verdict` enum had no `"unassessed"` value at all, though §19.2's
  degraded mode requires emitting exactly that for every cluster -
  added, with an `allOf` branch (`acordRef`/`deviation` both `null`);
  the degraded record reuses the cluster's own `evidenceRefs` rather
  than needing a schema relaxation. `contracts/C8/CanonicalCandidate/1.0.json`
  had no `vendorOnly` field at all, though Canonical Synthesiser's own
  guardrail G4 requires setting one - added as optional, defaulting
  `false`. Both regenerated, verified byte-reproducible across two runs,
  new positive fixtures added (`unassessed.json`, `vendor_only.json`),
  every pre-existing C7/C8 fixture confirmed to pass unmodified.
- **No separate "Extension Partitioner" or "Coverage Scorer" agent
  classes** - confirmed by direct research: neither is one of the four
  agents §7.5 "reproduces in full" (Semantic Resolver, ACORD Aligner,
  Canonical Synthesiser, Adversarial Critic), neither has its own
  guardrails or prompt block anywhere in the spec, and Canonical
  Synthesiser's own G3 ("placement MUST be produced by the deterministic
  rules in 9.7... the code supplies the placement") is the textual proof
  that placement happens inside Canonical Synthesiser's own flow.
  `algorithms/placement.py::place()` and `algorithms/coverage.py::coverage()`
  are plain deterministic functions - the latter with no agent wrapper
  at all ("Coverage Scorer... Pure arithmetic," per §7.7's own routing
  table - no LLM narrative is ever produced for it).
- **A genuinely different deterministic/agent relationship than
  Increment 7's.** I7's clustering had the deterministic algorithm
  decide confidently and the agent adjudicate only the leftover
  uncertain band. Here, the agent proposes on every item, and the code
  either constrains (guardrails) or supplies a field outright.
  Concretely: Canonical Synthesiser's own prompt gives the model no
  placement information at all (its `[INPUT]` block only ever contains
  cluster/alignment/member-attribute/naming-convention content), so its
  raw `placement`/`placementRule`/`obligation.level`/`vendorOnly` guesses
  (needed only to satisfy the schema's shape) are overwritten in
  `validate_semantics()` with the real, code-computed values - mutating
  `output` in place, a deliberate, documented, novel-but-justified use
  of the one mutable hook `agents/base.py::invoke()` offers (Python dict
  reference semantics mean the same object is carried through guardrails,
  write and route afterward). A "guardrail rejects the model's guess"
  design was considered and rejected: the model was never given the
  information needed to guess correctly, so that guardrail would fire on
  nearly every real invocation.
- `algorithms/naming.py`: Section 9.9's `check_name()` verbatim, reusing
  `algorithms.profiling.canonical_tokens`/`config.settings.ClusteringConfig.abbreviations`
  directly rather than a third tokenisation implementation. A real,
  caught design gap: `contracts/C8/CanonicalCandidate/1.0.json`'s
  `dataType` field is constrained to the same bare primitive enum as C5
  (string/integer/decimal/...), with no room for Rule 4's richer
  canonical type names ("MonetaryAmount", "Identifier") - `check_name()`
  itself stays fully spec-faithful and independently tested, but
  Canonical Synthesiser's own wiring of it honestly hardcodes
  `denotes_money`/`denotes_identifier` to `False` rather than checking
  against a field that can never hold the value being asked for,
  documented as a gap to revisit once a contract carries a real
  canonical-type-name field.
- `algorithms/placement.py`: Section 9.7's `place()` verbatim.
  `PlacementContext`'s three workshop-decision callables
  (`absence_is_gap`/`intends_to_close`/`workshop_approved`) all default
  to `False` - "never guess" (the spec's own words) means the safe
  default is the conservative reading, and no workshop-decision-recording
  mechanism exists in this repo (matching Increment 6/7's own
  orchestrator-deferral precedent). `is_jurisdictional_regulatory`
  defaults to `False` too, for the same reason, even though the spec's
  own commentary only explicitly names the other three this way -
  "jurisdiction-specific regulatory" has no corresponding classification
  field anywhere in `C5.AttributeRecord` either, so it genuinely cannot
  be computed from data alone. `max_evidence_tier` is real - it reads
  `C5.AttributeRecord.evidenceTier` directly. A real pseudocode gap
  (`sole_region()`, referenced but never defined) resolved as a
  documented, deterministic alphabetically-first tie-break, the same
  class of gap as Increment 7's `lemmatise()`/`dedupe_blocks()`.
- `algorithms/coverage.py`: `Concept` (one per `ConceptCluster`, not per
  candidate - a cluster with no synthesised candidate at all becomes a
  `"gap"` concept, the spec's own named category for exactly this case:
  *"do not invent one... the concept returns to triage"*). `weight` for
  a gap concept is derived from the strongest obligation level across
  the cluster's own members, the only concept-agnostic anchor available
  when no candidate (and so no `weight` field) exists. `ratifying_sme`
  is populated only once a human has actually approved the candidate -
  "the platform proposes, humans ratify" working as intended, not a gap
  to route around. `coverage()`/`gap_register()` transcribe Section
  9.8 verbatim against these real shapes; `REGION_FLOOR`/`DOMAIN_TARGET`/
  `RESOLUTION` become a new `CoverageConfig`, mirroring `ClusteringConfig`'s
  own Increment 7 pattern exactly.
- `agents/acord_aligner.py`: `AcordAlignerAgent`, all four guardrails
  from §7.5.2. G1 ("verdict=fit REQUIRES an acordRef returned... in this
  invocation") is enforced via `validate_semantics`, not the V4
  guardrail list - `Guardrail.check`'s signature has no access to the
  agent instance, only `validate_semantics` (a bound method) does, the
  same framework constraint Repository Scout's anti-drop check and
  Semantic Resolver's invented-member check already work within. G3
  ("a forced fit is prohibited") is inherently a semantic judgment no
  structural check can fully verify - the real, honestly-limited proxy
  implemented flags a `partial` verdict whose own deviation text echoes
  misfit language.
- `agents/canonical_synthesiser.py`: `CanonicalSynthesiserAgent`. G1
  (clusterRefs non-empty) and G2 (the naming convention checker) are
  real, stateless V4 guardrails. G3/obligation/vendorOnly are enforced
  by construction in `validate_semantics` (see above), which also reuses
  `contracts.validators.check_i3_candidate_traces_to_attribute` directly
  to confirm every clusterRef genuinely traces to real data, not
  reimplemented. Section 9.7's own `[UNCERTAINTY]` block ("emit no
  candidate... the concept returns to triage") has no representation in
  C8's all-required-fields schema; `make_canonical_synthesiser_factory()`
  catches the resulting `WorkItemFailed` and returns `None`, which
  `algorithms.coverage.build_universe()` already treats as exactly that
  - a legitimate `"gap"` resolution, not an error.
- `golden/coverage/`: hand-authored real C5/C6/C8/exclusion JSON (the
  same precedent as Increment 5's `substrate/graph_fixture.json` -
  clusters/candidates are themselves synthesized artefacts with no "raw"
  format to parse them from). Plants exactly the acceptance test's own
  scenario: a clean, 3-region, ratified `claimId` concept resolving to
  `"core"`; a weight-5 `lossDate` concept with **no candidate
  synthesised at all** - the seeded unresolved mandatory attribute Gate
  1 must block on; an unratified `reserveAmount` candidate exercising
  Gate 3 alongside it; one corpus-level exclusion.
- 807 tests passing (up from 704 at I7), `mypy --strict` clean across
  171 source files, ~99.5% coverage overall (100% within every module
  this increment touched or added).
- Acceptance-test clause mapping: "Coverage is computed with a
  published denominator" -> `tests/algorithms/test_coverage_acceptance.py`
  asserts `denominator == len(universe)` and a populated `exclusions`
  register, validated against the real, unmodified C9 CoverageReport
  schema. "Gate 1 blocks correctly on a seeded unresolved mandatory
  attribute" -> same test - the seeded `cluster://loss-date` concept
  yields `gate1Pass is False` and a `gap_register()` entry with
  `reason="unresolved"`.

## I9 - what was built

- **The final increment of the 9-increment PoC.** No `AskUserQuestion`
  round was needed - unlike I7's clustering-architecture fork and I8's
  ACORD-Aligner-scope fork, the acceptance test's own three clauses
  directly dictate building the full mapping DSL/compiler/interpreter/
  transform-library/emitters/workshop-pack for real; there was no genuine
  architectural fork to choose between, only implementation judgment
  calls (documented below, not asked).
- **A genuine contract gap, same rigor as I4/I6/I7/I8's own fixes**:
  `contracts/C10/MappingSpec/1.0.json`'s `tests` field was a placeholder
  array at Increment 1 ("populated by Increment 9's
  generate_round_trip_tests()"). Appendix C's own worked example shows
  `tests.roundTrip` as an **aggregate summary object**
  (`generated`/`assertion`/`declaredLosses`/`result`), not one row per
  synthesised seed - fixed to that real, structured shape. Regenerated,
  verified byte-reproducible across two runs, new positive/negative
  fixtures added, every pre-existing C10 fixture confirmed to pass
  unmodified.
- **`mapping/interpreter.py::Plan.reverse()` - a real spec gap, resolved
  symmetrically.** Section 10.6's own reference interpreter shows
  `forward()` in full but `reverse()` is only ever *referenced* (by
  Section 10.5's own round-trip pseudocode), never given a body.
  `reverse()` walks the same steps, applies each transform's declared
  reverse callable (`mapping/transforms.py`) in reverse chain order, and
  reuses the identical `on_failure` dispatch. Two transforms have no
  reverse at all (`coalesce`, `constant` used as an entry's own top-level
  transform - the spec's own "Reverse is undefined" / "n/a" table
  entries): such a step is marked non-reversible at compile time and
  `reverse()` skips it silently rather than raising, since it is a
  structural, not a data, condition. `constant("GBP")` appearing as a
  *nested argument* (Appendix C's own
  `toMonetaryAmount(currency=constant("GBP"))`) is a different thing
  entirely, resolved by `mapping/parser.py` to a plain literal at parse
  time - not an invocation of the `constant` transform at all.
- **A second, genuinely undocumented gap in the grammar itself**: Section
  10.2's EBNF defines no `default:` value field for an entry at all, yet
  Section 10.6's own `_handle()` pseudocode has an `onFailure: default`
  branch that writes one. Since the DSL gives no way to author a default
  value, `Plan._handle()` writes `None` - the only default the grammar
  can express - documented plainly rather than inventing an unspecified
  field.
- **A builder-added static check, D1**, beyond the spec's literal T1-T4:
  `compile_spec()` rejects a bidirectional entry whose transform chain
  contains `coalesce` or a top-level `constant` (both have no reverse),
  since a bidirectional spec's own promise cannot be kept for that entry.
- **The transform library's own "Reverse" column names five functions
  that are never themselves legal `transform:` line names** (formatDate's
  counterpart is `parseDate`, a real row - fine - but `toLocalDate`,
  `valueMapInverse`, `amountOf`, `valueOf` and `split` are not among the
  14 forward-facing names). Implemented as private functions in
  `mapping/transforms.py`, never registered under their own `TRANSFORMS`
  key - an SME cannot write `transform: valueOf(...)`, only the
  interpreter invokes them internally when undoing a step.
- **`decompose`/`compose` reversibility** required a builder resolution
  the spec's own worked example never exercises (no decompose/compose
  usage appears anywhere in Appendix C): both `pattern` (a Python regex
  with named groups) and `template` (a Python format string) are
  required on any entry using either transform, even though only one is
  "forward-relevant" - the other is what makes the step reversible at
  all.
- **`coalesce`'s own `[T] -> T` signature** assumes a single, already
  multi-valued input, not several independent region paths - the
  grammar's one-`region:`-per-entry design has no room for a multi-path
  read, and the spec gives no worked coalesce example to resolve this
  against otherwise. This reference interpreter reads `[T]` from a
  single `region_path` pointing at an array-shaped source.
- **`ReleaseManifest` (Section 11.4) is NOT a 12th C-numbered contract.**
  Appendix A's own contract index closes the list at C11, and
  `contracts/C11/RunManifest/1.0.json` is a genuinely different *run*
  record (trigger/budget/state), with no room for `version`/`artefacts`/
  `coverage`/`conformance`/`decisions`/`approvers`/`signature`. Built
  instead as a real, hand-written JSON Schema under
  `emit/schemas/release_manifest.schema.json` - heavier than the
  `Concept`/`Block`/`ProfiledAttribute` dataclass-only precedent,
  deliberately, because this artefact is explicitly emitted, signed and
  externally consumed the way a contract is. Section 6.3's `Release`
  graph-node type (`substrate/graph.py::ReleaseProps`, Increment 5) turns
  out to be the graph-lineage projection of this fuller document, not a
  separate design - both were already documented as "real artefact, not
  a C-contract" the same status class.
- **C8's own `dataType` gap (already documented at I8) recurs here**:
  `emit/schema.py` has no signal that a candidate's real value is a
  MonetaryAmount or Identifier shape (C8's `dataType` stays the bare
  primitive enum) - such a candidate emits as a plain `object`, the same
  honest limitation as I8's `denotes_money`/`denotes_identifier`
  guardrail wiring, not silently guessed around with a naming heuristic.
- **No new third-party dependency.** "Emitted schemas validate" is proven
  with the already-available `jsonschema` library
  (`Draft202012Validator.check_schema()` against every emitted document,
  plus real instances validated against the emitted entity schemas) -
  this repo has added exactly 3 dependencies across 8 prior increments,
  all load-bearing, and §2.3's own `openapi-spec-validator` mention was
  never actually added even at Increment 3 (OpenAPI parsing).
- `mapping/transforms.py`: all 14 closed-vocabulary transforms (Section
  10.3), each forward function sharing one signature `(value, **kwargs)
  -> Any` with its (where defined) reverse, so the interpreter dispatches
  generically in both directions without per-transform special-casing.
- `mapping/parser.py`: a hand-rolled scanner for Section 10.2's grammar
  (not a generated parser - the grammar is deliberately tiny), enforcing
  the 3-call chain limit and resolving the `constant(...)`-as-argument
  case.
- `mapping/compiler.py`: `compile_spec()` - T1 Totality, T2 weight rule,
  T3 type fit, T4 value-map completeness (plus its own injectivity
  check), D1. `canonical: CanonicalModel` (the spec's own pseudocode
  parameter - no such type exists anywhere in this repo) is resolved as
  a plain `{canonicalPath: dataType}` projection the caller builds from
  whatever C8 candidates are in hand; T3 is skipped, not failed, for a
  canonical path with no known type yet.
- `agents/mapping_generator.py`: the twelfth and final agent (Appendix
  B). One invocation covers one whole region contract (the prompt's own
  `[INPUT]` block passes the complete, in-scope attribute list), a
  different granularity than ACORD Aligner/Canonical Synthesiser's own
  per-cluster calls - which is what makes G1 (Totality) a real,
  per-invocation guardrail here (implemented via `validate_semantics`,
  since `Guardrail.check` has no access to the agent instance, the same
  framework constraint I8 already documented). G2-G5 are real, stateless
  V4 guardrails reusing `mapping/parser.py`/`mapping/transforms.py`
  directly. Unlike ACORD Aligner/Canonical Synthesiser's own worked
  prompts (both missing an `[INJECTION]` block at I8, fixed by adding
  one), Appendix B's own prompt text already has a real one - transcribed
  verbatim, no fix needed.
- `emit/schema.py`, `emit/common_schemas.py`: one JSON Schema per entity
  from real C8 data (core attributes only; extension attributes are never
  inlined, only `$ref`-referenced), the six static `common/` documents,
  and `serialise()` - sorted keys, two-space indent, LF endings, written
  as bytes (never a text-mode file handle) so no platform substitutes
  CRLF.
- `emit/openapi.py`: a pure projection - `components.schemas` is bare
  `$ref`s into the entity schemas, `paths: {}` (Section 12's HTTP APIs
  stay out of scope).
- `emit/logical_model.py`: Section 11.3's JSON-LD export, built from real
  C8 data plus two caller-supplied maps (evidence-by-candidate,
  alignment-by-entity) this module has no way to derive on its own -
  keeping it fully hermetic. `ratifiedBy.session` substitutes
  `ratification.decidedAt` (no session-naming field exists anywhere in
  this repo's data model), the same class of honest substitution as
  `algorithms/coverage.py::sole_region()`'s own tie-break.
- `emit/release.py` + `emit/schemas/release_manifest.schema.json`:
  `ReleaseManifest`, `build_release_manifest()`,
  `validate_release_manifest()`. `signature` is a caller-supplied PoC
  placeholder - no real signing infrastructure exists in this repo, the
  same status `EgressConfig.ledger_signing_key` already carries.
- `emit/workshop_pack.py`: `assemble_pack()` - a real directory of files
  plus one indexing `WorkshopPackManifest` (sha256 + description per
  file, a `declaredLosses` roll-up pulled from every compiled mapping
  spec's own round-trip summary). Writes a real, labelled
  `acord-alignment.md` manual-completion section (Section 19.2's own
  degraded-mode language), since ACORD data has been unavailable since
  Increment 1 - the gap is shown honestly, not silently omitted or
  faked.
- `golden/mapping/`: `region_attributes.json` (7 real C5 AttributeRecord
  entries) + `uk-claims-v3.mapping.json` (Appendix C's own worked mapping
  spec, transcribed as real C10 JSON) - one entry
  (`coveragesInForce[].limit`) flattened to a non-array path
  (`coverageLimit`/`Cover.LimitAmount`), since the reference
  interpreter's own `read_path`/`write_path` do not resolve `[]`
  segments (a documented PoC scope boundary, not a defect). Reuses
  `golden/coverage/{candidates,clusters}.json` (Increment 8's own golden
  data) directly for the emission side rather than duplicating a
  parallel fixture set.
- 973 tests passing (up from 807 at I8), `mypy --strict` clean across
  199 source and test files (matching the CI invocation), ~97% coverage
  overall (100% within `mapping/` and `emit/`, the packages this
  increment added).
- Acceptance-test clause mapping (`tests/emit/test_i9_acceptance.py`):
  "Emitted schemas validate" -> every entity/extension/OpenAPI document
  passes `Draft202012Validator.check_schema()`, and a real candidate
  instance validates against its own emitted entity schema. "Every
  round-trip test passes or its loss is declared" -> the golden
  `uk-claims-v3` mapping spec compiles and round-trips with zero
  undeclared losses, its one real declared loss
  (`ClaimHeader.LossDate`, kind `precision`) matching Appendix C's own
  worked outcome exactly. "The pack is complete enough to run a real
  session from" -> `assemble_pack()` over the same golden data writes
  every manifest-listed file with a matching sha256, including at least
  one schema per entity, a passing mapping spec, the real coverage
  report/gap register, the release manifest, and the ACORD manual-
  completion section.
- **Out of scope as of this final increment (later reversed - see the
  Section 12 + orchestrator entry below)**: Section 12's run-control/
  registry/workshop HTTP service APIs and the S1-S8 orchestrator state
  machine were both still unbuilt at I9's own completion. ACORD Reference
  Architecture content (permanently unlicensed since Increment 1); a
  live re-proof of the recursive-CTE lineage query (proven once, for
  real, at Increment 5 via `pytest.mark.db` - I9's logical-model export
  only has to produce documents *consistent with* what that query would
  return); `RunManifest.state` as a closed enum (still an open string)
  remain true as of this entry.

## Section 12 Internal Service APIs + hermetic driving orchestrator (2026-09-01, beyond the 9-increment guide)

Built at the user's own explicit request, after the 9-increment guide's
own completion - not "Increment 10." Two things I9's own "out of scope"
note above named are no longer true: Section 12's HTTP APIs are real, and
a real (if deliberately bounded) orchestrator now drives runs through
them.

- **The orchestrator's own hermetic boundary**: `pipeline/orchestrator.py::
  create_run()` drives a run synchronously through S1 (real `GitConnector`
  instances over `golden/git/claims-{us,uk,eu}/`, sealed via
  `connectors.manifest.assemble_corpus_manifest` - the same real path
  `tests/connectors/test_golden_corpus_e2e.py` already proves), S3 (real
  `parsers.router.parse` + `algorithms.profiling.profile` per artefact),
  S4 (real `algorithms.clustering.run_clustering`, "zero LLM dependency"
  by its own Increment 7 design), then seals a real TRIAGE checkpoint and
  stops - zero live Postgres, zero live Anthropic key required for any of
  it. This boundary is not arbitrary: it is exactly where this repo's own
  existing code already drew the deterministic/probabilistic line.
  `resume_after_checkpoint()` continues into ACORD Aligner (degrades
  automatically) and Canonical Synthesiser only when a real model
  provider is actually configured; otherwise the run stops at a real,
  honestly-labelled `AWAIT_MODEL_PROVIDER` state, never faking a decision.
- **A real bug fixed empirically, not assumed**: `connectors.manifest.
  assemble_corpus_manifest`'s own `connectors_by_system` dict is keyed by
  `Connector.system` alone - every `GitConnector` reports `system="git"`
  regardless of the region it was constructed with, so passing three
  region-tagged connectors as one combined `sources` list makes the last
  one silently shadow the other two for every `fetch()` call. Discovered
  by the orchestrator's own S1 step actually failing with a real git
  error the first time it ran end to end. Fixed by issuing three
  independent `assemble_corpus_manifest` calls (one connector each, no
  collision) and merging the results into one `C4Corpusmanifest`
  afterward, with `corpusHash` recomputed for real over the combined
  artefact set.
- **A second real discovery**: `agents/semantic_resolver.py`'s own
  `assemble_context()` calls `SubstrateApi.search()` (hybrid BM25+vector
  retrieval), which genuinely needs a live `SubstrateDb` connection -
  unlike ACORD Aligner's `acord_lookup()` and Canonical Synthesiser's
  `get_attribute()`, neither of which ever touches the database. Semantic
  Resolver's own review-band adjudication is therefore deliberately NOT
  part of the automatic continuation (gating the whole continuation on
  "a live Postgres, if the review band happens to be non-empty" would
  contradict the model-provider-only gating design) - review-band
  material stays exactly where `create_run()` sealed it, for a caller
  with real DB access to resolve separately via the existing
  `agents.semantic_resolver.make_semantic_resolver_adjudicator` factory.
- **A genuine, previously-unwired gap closed in passing**: `RunManifest.
  budget` (populated from a real `POST /v1/runs` request body) was never
  actually consumed anywhere - the orchestrator's own `RunContext` used a
  hardcoded budget. Fixed to build `agents.model_gateway.Budget.
  from_contract(manifest.budget)` - a factory method that existed for
  exactly this purpose but had never been called anywhere in this repo
  until now.
- **`emit/release.py`'s `ReleaseManifest` gained a `signed_at` field** -
  Section 12.3's own `GET /v1/registry/{domain}/releases` response shape
  (`{semver, signedAt, coverage, conformance}`) names it, but Section
  11.4's worked example (which `emit/schemas/release_manifest.schema.json`
  was built from at Increment 9) never included it - a genuine contract
  gap discovered wiring the registry API against that schema, closed the
  same way I4/I6/I7/I8/I9 closed their own.
- **A guardrail-violation robustness gap fixed in the orchestrator's own
  synthesis loop**: `agents.canonical_synthesiser.make_canonical_
  synthesiser_factory`'s own `_synthesise()` catches `WorkItemFailed` but
  not `GuardrailViolation` (zero retries by design, Section 7.6). One
  cluster's own naming/tracing violation - discovered for real: the
  golden corpus's own "status" cluster trips `algorithms/naming.py`'s
  documented, intentionally trigger-happy region-marker check ("us"
  matches inside "status") - must not abort synthesis for every other
  cluster in the run. `resume_after_checkpoint()` now catches it per
  cluster, journals the rejection, and continues.
- `api/` (new top-level package): a real FastAPI application
  (`create_app()`) implementing all of Section 12.2 (run control), 12.3
  (registry), and 12.4 (workshop/decisions) as real HTTP routes over
  real, already-tested functions - no business logic reimplemented in
  the HTTP layer. RFC 9457 problem-details for the full Section 12.5
  error table, real cursor pagination and idempotency-key handling (both
  documented PoC placeholders, not production-grade), a bearer-token
  stand-in for Section 12.1's own real mTLS/OAuth2 model. `GET .../diff`
  (registry) is the one genuinely new piece of business logic in the
  whole package - nothing existing computes a release diff; `breaking`
  is a documented heuristic and `causeAttribution` an honestly-labelled
  structural stub, not real provenance.
- `pipeline/registry_store.py` and `pipeline/workshop_store.py` (new) -
  file-based persistence for signed releases and workshop records,
  mirroring `RunStore`'s own established convention.
- New dependencies, all load-bearing: `fastapi`, `uvicorn[standard]`,
  `python-docx`, `openpyxl` (dev: `httpx`, `types-openpyxl`) - this
  repo's first genuinely new dependency *category* since `anthropic` at
  Increment 6.
- 1112 tests passing (up from 1045 immediately after I9), `mypy --strict`
  clean across 228 source and test files, ~99% coverage within every
  package this work added or extended (`pipeline/orchestrator.py`,
  `pipeline/registry_store.py`, `pipeline/workshop_store.py`, the
  extended `pipeline/run_store.py`, and all of `api/`) - the repo's
  global `fail_under = 85` gate stays the honest floor for the whole
  suite (97.5% overall), not a per-package overclaim.
- **Still, honestly, out of scope after this work**: real mTLS / OAuth2
  client-credentials / workload identity (Section 13) - stood in by a
  static bearer token only. A persistent/distributed idempotency store
  and cryptographically opaque cursor tokens - both in-process PoC
  placeholders. Section 14 observability. RATIFY/ARB checkpoint sealing
  (no orchestrator path produces either yet - only TRIAGE). Semantic
  Resolver's review-band adjudication and mapping generation as part of
  the automatic post-checkpoint continuation (both real, existing, just
  not wired into `resume_after_checkpoint()` - see above). True
  `causeAttribution` provenance on the registry diff endpoint.
  `RunManifest.state` as a closed enum. Any domain other than `claims`
  in the hermetic orchestrator path. ACORD Reference Architecture content
  (still permanently unlicensed).

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
