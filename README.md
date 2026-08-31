# Canonical Model Generation Platform

A platform that derives canonical domain models from regional API estates. This project reads source repositories, interface definitions, and API contracts; normalizes them; clusters attributes; aligns to ACORD Reference Architecture; and proposes canonical models with comprehensive coverage analysis.

## Overview

The Canonical Model Generation Platform helps insurance organizations manage multiple regional API contracts by:

1. **Ingesting** diverse sources (XSD, WSDL, OpenAPI, custom contracts)
2. **Normalizing** data across different formats and regions (US, UK, EU)
3. **Clustering** semantically similar attributes across regions
4. **Aligning** to industry standards (ACORD Reference Architecture)
5. **Generating** canonical domain models with full lineage tracking
6. **Ratifying** through human-in-the-loop approval workflows

## Key Features

- **Multi-region support**: US, UK, EU regions with unified canonical models
- **Multiple input formats**: XSD, WSDL, OpenAPI 3.1, JSON Schema, custom contracts
- **AI-powered alignment**: LLM-based semantic understanding and clustering
- **Bidirectional mapping**: Region-to-canonical and canonical-to-region transformations
- **Comprehensive coverage analysis**: Gap reports and coverage metrics
- **Audit trail**: Full lineage and justification for all mappings
- **Human-in-the-loop**: Checkpoint-based approval workflow
- **Extensible architecture**: DSL-based mapping specifications

## Implementation Language

- **Pipeline & Agent Code**: Python 3.12
- **Data Contracts**: JSON Schema 2020-12 (`contracts/`), generated into Pydantic v2 (`generated/`)
- **Configuration & Mappings**: YAML
- **Output Formats**: OpenAPI 3.1, JSON Schema, Logical models

## Build Status

This repository is being rebuilt against `TECHNICAL_SPECIFICATION.txt` (the
authoritative source of truth) following the PoC Build Guide's nine
increments (Section 17), in order: contracts before code, the sanitisation
gate before any real evidence moves, deterministic components before
probabilistic (agent) ones, coverage before emission.

**All nine increments are complete.** Increment 1 ("Skeleton and
contracts"): repository layout, CI, `mypy --strict`, all eleven data
contracts as JSON Schema with generated Pydantic models, cross-artefact
invariant validators, and a fixture suite. Increment 2 ("Connectors and
manifest"): real Git and Confluence-fixture connectors, two-pass relevance
filtering, and corpus manifest assembly/sealing/persistence, proven
end-to-end over a real golden corpus. Increment 3 ("Parsers to IR"):
OpenAPI/XSD/WSDL/Avro parsers producing `AttributeRecord` (the IR)
directly, the authoritative type-normalisation lookup, and the attribute
profiler - the planted `xsd:choice` and untyped-date golden fixtures prove
the spec's own worked test and the parser/profiler separation
structurally. Increment 4 ("Gate and ledger"): the real L0-L4
sanitisation ladder, keyed tokenisation, policy decision point, and a
hash-chained, signed egress ledger, replacing Increment 2's placeholder
sanitisation. Increment 5 ("Substrate and retrieval"): a real
PostgreSQL + pgvector knowledge substrate - chunking, a mock embedding
pipeline, a concept graph with a recursive-CTE lineage query, and
hybrid BM25 + vector search behind `SubstrateApi`. Increment 6 ("Agent
runtime"): the `Agent` base contract's ten-step invocation path, a tool
gateway with per-agent authorisation and audit, a model gateway with
budget enforcement and a **real Anthropic API integration**, the V1-V5
validation ladder, and two real agents (Repository Scout, Schema
Interpreter) proven end to end. Increment 7 ("Clustering and
conflicts"): a fully deterministic blocking/similarity/clustering/
homonym-splitting/conflict-classification pipeline (zero LLM
dependency), the Semantic Resolver agent adjudicating only the
review-band material that pipeline sets aside, and a real agent
evaluation harness (`eval/`) gated on Cluster F1 and homonym recall.
Increment 8 ("Synthesis and coverage"): ACORD Aligner (built in full,
though its own guardrail routes every real run in this repo to Section
19.2's deterministic degraded mode, since ACORD data has been
unavailable since Increment 1) and Canonical Synthesiser proposing
canonical attributes with the code - not the model - supplying
placement, obligation strength and vendor-only flagging outright, plus
real coverage computation, gap register and Gate 1/2/3 evaluation.
Increment 9 ("Emission and workshop pack", the final increment): the
mapping specification DSL (grammar, a 14-entry closed transform library,
a real compiler enforcing T1-T4 plus a builder-added D1, a reference
interpreter with a real `reverse()` the spec itself never shows), Mapping
Generator (the twelfth and final agent), and `emit/`'s real, validating
JSON Schema/OpenAPI/logical-model/release-manifest emitters, assembled
into a concrete workshop pack an SME can run a real session from. See
`docs/contracts.md` and `docs/increments.md` for the full
per-increment record.

A previous implementation (`archive/legacy_src/`) diverged from the spec in
several fundamental ways (random-UUID identity instead of the spec's
deterministic `evref://`/`attr://` scheme, different similarity-scoring
weights, an agent framework built before the sanitisation gate it depends
on) and was archived rather than extended; it was not reused at Increment 3
either, since its `AttributeRecord` construction was built against the old,
incompatible model shape - only its OpenAPI/JSON-Schema traversal *shape*
informed the new parsers, not its code.

## Project Structure

The repository follows the layout mandated by the PoC Build Guide (Section
17.4). Directories not yet populated carry a `README.md` stating which
increment populates them.

```
canonical-model-generation/
  contracts/          C1-C11 JSON Schema 2020-12 contracts (Increment 1)
  generated/           Pydantic models generated from contracts/ - never hand-edited (Increment 1)
  config/               Platform configuration: settings.py, platform.yaml (Increments 1-2)
  prompts/{agent}/      Versioned agent prompt templates (repository-scout - I6; semantic-resolver - I7; acord-aligner, canonical-synthesiser - I8)
  agents/               Agent runtime: Agent ABC, model gateway (real Anthropic wiring), validation ladder, Repository Scout, Schema Interpreter (I6), Semantic Resolver (I7), ACORD Aligner, Canonical Synthesiser (I8)
  tools/                 Tool gateway: registry, authorisation/audit, real handlers for artefact.write/spec.parse/substrate.*/acord.lookup (Increment 6 - built)
  connectors/           Git/Confluence connectors, relevance filtering, corpus manifest (Increment 2 - built)
  parsers/               OpenAPI/WSDL/XSD/Avro parsers, type normalisation (Increment 3 - built; code_inference.py deferred)
  gate/                  Sanitisation ladder, tokenisation, egress ledger (Increment 4 - built)
  substrate/             Chunking, embeddings, vector + concept graph, substrate-api (Increment 5 - built, real Postgres + pgvector)
  pipeline/               Orchestration: run store persistence, journal, triage export (Increments 2-7 - built), state machine (out of PoC scope - see docs/increments.md)
  algorithms/            Attribute profiling (I3); blocking, similarity, graph, conflict classification, clustering (I7, zero LLM dependency); naming, placement, coverage + gap register (I8 - built)
  mapping/               Mapping DSL: grammar, 14-entry transform library, compiler (T1-T4+D1), reference interpreter, round-trip test generation (Increment 9 - built)
  emit/                   Entity/extension/common JSON Schema emitters, OpenAPI projection, JSON-LD logical model export, release manifest, workshop pack assembly (Increment 9 - built)
  api/                    Internal service APIs (run control, registry, workshop) (Increment 12)
  golden/                Golden corpus, built incrementally (Increments 2-9 - see golden/README.md)
  eval/                  Agent evaluation harness: thresholds, worst-of-5 gating (Increment 7 - built, for Semantic Resolver)
  infra/                 docker-compose.yml (local Postgres + pgvector, Increment 5)
  docs/                   Detailed documentation, updated alongside contract/agent changes
  tests/
    agents/                Agent ABC, model gateway, prompt render, validation ladder, Repository Scout, Schema Interpreter, Semantic Resolver, ACORD Aligner, Canonical Synthesiser, Mapping Generator, I6/I7/I8/I9 acceptance tests
    algorithms/            Profiling, blocking, similarity, conflict, clustering, naming, placement, coverage tests, I7/I8 acceptance tests
    connectors/            Connector, relevance-filter, manifest, and golden-corpus e2e tests
    contracts/            Schema + generated-model fixture and invariant tests
    emit/                   Schema/OpenAPI/logical-model/release-manifest/workshop-pack tests, I9 acceptance test
    eval/                  Eval harness tests (worst-of-5 gating, real-model llm test)
    fixtures/              Per-contract positive/negative fixtures, invariant bundles
    gate/                  Detectors, tokenisation, policy, ledger, Increment 4 acceptance tests
    mapping/               Transform library, parser, compiler, interpreter, round-trip generation tests
    substrate/             Chunking, embedding, graph, search, ingest, api, Increment 5 acceptance tests (mostly pytest.mark.db)
    tools/                 Tool gateway authorisation/schema/journalling tests
    parsers/               Parser, type-normalisation, and router tests
    pipeline/              Run-store tests (incl. triage export)
    unit/                  Unit tests (validators, config)
  archive/legacy_src/      Pre-rebuild implementation, retained for reference/cherry-picking
  .github/workflows/       CI
  pyproject.toml          Project configuration
  README.md                This file
  TECHNICAL_SPECIFICATION.txt  Full technical specification (source of truth)
```

## Getting Started

### Prerequisites

- Python 3.12+ (the dev environment here currently runs 3.13; CI pins exactly 3.12)
- Docker Desktop (optional at Increment 1 - only needed once `infra/docker-compose.yml` is actually used, from Increment 5 onward). If port 5432 is already taken by another local Postgres install, remap the host port in `infra/docker-compose.yml` and point `CMGP_STORAGE__POSTGRES_DSN` at it - see that file's own comment.
- An Anthropic API key (optional until Increment 6's agent framework is
  exercised for real - `pytest.mark.db`/`pytest.mark.llm` tests skip
  cleanly without their respective prerequisite, so neither is required
  just to run the rest of the suite):
  1. Create a key at [console.anthropic.com](https://console.anthropic.com)
     (Settings -> API Keys).
  2. Set it in your shell before running anything that makes a real
     model call: `export ANTHROPIC_API_KEY=sk-ant-...` (or the
     PowerShell equivalent, `$env:ANTHROPIC_API_KEY = "sk-ant-..."`).
     `agents/model_gateway.py::anthropic_provider` reads it from the
     environment lazily, on the first real call only - it is never
     required to import this repo's code, run the hermetic test suite,
     or construct a `ModelGateway` with an injected fake provider.
  3. Run `pytest -m llm` to exercise the real Anthropic-backed tests
     once the key is set.

### Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

### Regenerating models from contracts

`generated/` is produced entirely from `contracts/` and must never be
hand-edited. After changing any file under `contracts/`, regenerate and
commit both together in the same change:

```bash
python scripts/generate_models.py
git add contracts/ generated/
```

CI fails the build if `generated/` doesn't match what
`scripts/generate_models.py` produces from the committed `contracts/`.

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage report (fails under 85%, per pyproject.toml)
pytest --cov=generated --cov=contracts --cov=config --cov=connectors --cov=pipeline --cov=parsers --cov=algorithms --cov=gate --cov=substrate --cov=agents --cov=tools --cov=eval --cov=mapping --cov=emit --cov-report=term-missing

# Run just the contract/fixture tests
pytest tests/contracts/

# Run just the Increment 2 acceptance test (real connectors over the golden corpus)
pytest tests/connectors/test_golden_corpus_e2e.py

# Run just the Increment 3 acceptance test (the spec's own worked xsd:choice test, and profiling)
pytest tests/parsers/test_xsd.py tests/algorithms/

# Run just the Increment 4 acceptance test (masked example, licence-blocked exclusion, ledger)
pytest tests/gate/test_acceptance.py tests/gate/test_ledger.py

# Run just the Increment 5 acceptance test (deterministic retrieval, four-hop lineage) -
# needs a live Postgres: docker compose -f infra/docker-compose.yml up -d
pytest tests/substrate/test_substrate_acceptance.py

# Run just the Increment 6 acceptance test (denied tool call, retry-then-escalate, injection resistance)
pytest tests/agents/test_agent_runtime_acceptance.py

# Run just the Increment 7 acceptance test (planted synonyms cluster, planted homonym doesn't merge) -
# zero LLM, zero DB
pytest tests/algorithms/test_clustering_acceptance.py

# Run the Increment 7 eval-harness tests (worst-of-5 gating arithmetic)
pytest tests/eval/

# Run just the Increment 8 acceptance test (published denominator, Gate 1 blocks
# on a seeded unresolved mandatory attribute) - zero LLM, zero DB
pytest tests/algorithms/test_coverage_acceptance.py

# Run just the Increment 9 acceptance test (emitted schemas validate, round-trip
# tests pass or declare their loss, workshop pack complete) - zero LLM, zero DB
pytest tests/emit/test_i9_acceptance.py

# Run the mapping DSL / compiler / interpreter / round-trip generator tests
pytest tests/mapping/

# Run the tests requiring a real Anthropic API call (skip cleanly without ANTHROPIC_API_KEY)
pytest -m llm
```

### Development

```bash
mypy --strict generated contracts config connectors pipeline parsers algorithms gate substrate agents tools eval mapping emit tests
black contracts/ config/ connectors/ pipeline/ parsers/ algorithms/ gate/ substrate/ agents/ tools/ eval/ mapping/ emit/ tests/ scripts/
isort contracts/ config/ connectors/ pipeline/ parsers/ algorithms/ gate/ substrate/ agents/ tools/ eval/ mapping/ emit/ tests/ scripts/
```

## Configuration

Configuration is layered: platform defaults (`config/platform.yaml`) under
environment variable overrides (`CMGP_` prefix). See `config/settings.py`
and `docs/contracts.md` for details.

Key configuration areas:
- Model tier routing (`fast`/`high`/`critic`, provider-abstracted via
  `tier_id`). Since Increment 6, each tier also carries a concrete
  `model_id` (`config/platform.yaml`) that `agents/model_gateway.py`
  resolves to a real Anthropic model - a deliberate, user-confirmed
  departure from Increment 1's original "no concrete provider/model
  named anywhere" framing (Section 13/D3), once the agent framework
  needed a real provider to call.
- Storage settings (Postgres + pgvector, `infra/docker-compose.yml`)
- Feature flags (`acord.ingestion.enabled`, `inference.enabled`,
  `critic.secondary_provider`, `gate.dpo_override.enabled`,
  `emission.strict_determinism`)
- Egress fail-mode (hard-locked to `closed`)

## Architecture Highlights

### Data Contracts (Section 3)
- **C1**: SourceArtefact - Input data from regions
- **C2**: SanitisationRecord - classification ladder result per artefact
- **C3**: EgressLedgerEntry - hash-chained egress audit trail
- **C4**: CorpusManifest - Metadata and lineage tracking
- **C5**: AttributeRecord - Normalized attribute representation
- **C6-C8**: ConceptCluster, AlignmentRecord, and CanonicalCandidate models
- **C9**: CoverageReport / GapEntry
- **C10**: MappingSpec - region-to-canonical mapping DSL document
- **C11**: RunManifest and JournalEvent - Execution tracking

See `docs/contracts.md` for the full field reference and which contracts
are verbatim spec transcriptions vs. interpreted/synthesized designs.

### Ingestion Pipeline (Section 4)
- Connectors for XSD, WSDL, OpenAPI, custom schemas
- Type normalization and code contract inference
- Incremental ingestion support
- Relevance filtering

### Core Algorithms (Section 9)
- Attribute profiling and similarity scoring
- Blocking strategies for efficiency
- Semantic clustering
- ACORD alignment scoring
- Coverage computation

### Agent Framework (Section 7)
- LLM-based agents for semantic understanding
- Tool gateway for safe external access
- Validation ladder for output quality
- Prompt templates and agent specifications
- Retry and escalation logic

### Orchestration (Section 8)
- State machine-based run orchestration
- Work item fan-out for parallel processing
- Checkpoint-based human approval gates
- Incremental resume capability

## Major Components

### 1. Ingestion and Normalization
Reads diverse input formats and produces normalized intermediate representation.

### 2. Knowledge Substrate
Concept graph and semantic knowledge base supporting attribute understanding.

### 3. Agent Framework
LLM-powered agents for semantic analysis, alignment, and decision making.

### 4. Core Algorithms
Clustering, similarity scoring, profiling, and coverage analysis.

### 5. Orchestration Engine
State machine managing pipeline execution with checkpoints for human ratification.

### 6. Registry
Versioned storage and query system for canonical models and artefacts.

### 7. Mapping DSL
Domain-specific language for expressing transformations between regional and canonical models.

### 8. Sanitisation Gate
Ensures PII removal and data governance compliance before output.

## Output Artefacts

Per domain release, the platform produces:

1. **Canonical Contracts**: OpenAPI 3.1 with shared JSON Schema
2. **Mapping Specifications**: Bidirectional with generated round-trip tests
3. **Logical Model**: Tool-neutral with glossary and lineage
4. **Coverage Reports**: Gap analysis and metric dashboards
5. **Release Manifest**: Signed approval document

## Workflow

```
Ingestion -> Normalization -> Clustering -> Alignment -> Analysis
Parse XSD     Type norm        Similarity    ACORD        Coverage
Parse WSDL    Code infer       scoring       alignment    reports
Parse OpenAPI Blocking         Candidates    Decision      Gaps
Extract JSON  Chunking         voting        points
```

Then:
```
-> Generation -> Sanitisation -> Registry -> Human Ratification -> Release
   OpenAPI       PII removal    Version &    Review &              Signed
   Mappings      Governance     index        approve               manifest
   Schemas       Verification   Tagging      Adjust
   Logical       Audit trail    Query        Retry as needed
   models
```

## Key Constraint

**The platform proposes. Humans ratify.**

No artefact reaches release without named human approver. This shapes the entire architecture, particularly in checkpoint states and evidence tracking.

## Wave 1: Claims Domain

Initial wave focuses on Insurance Claims:
- Claim core
- Party (shared)
- Address (shared)
- Money (shared)

## Security & Compliance

- Identity and access control
- Network security
- Prompt injection protection
- Audit logging for all decisions
- Data sanitisation and PII removal
- Governance compliance

## Observability

- Comprehensive logging and tracing
- Prometheus metrics
- OpenTelemetry support
- Cost tracking and controls
- Run analytics and dashboards

## Testing Strategy

- Unit tests for components
- Golden corpus for regression
- Deterministic algorithm tests
- Agent evaluation harness
- Round-trip mapping validation
- Re-baseline testing

## Documentation

See `TECHNICAL_SPECIFICATION.txt` for the complete 80+ page technical specification covering:
- Full component specifications
- Data contract definitions
- Algorithm descriptions
- API contracts
- Security requirements
- Operational procedures

See `docs/contracts.md` and `docs/increments.md` for the current
implementation's own documentation, kept in sync with the spec per the
Definition of Done (Section 17.5).

## License

Proprietary - Internal and named third parties only

## Contact

For questions or issues, contact the Integration Architecture team.

## Contributing

See `CONTRIBUTING.md` for development guidelines.

---

**Status**: Draft for Technical Review (v0.1) - Increments 1-9 of 9 (PoC Build Guide, Section 17) complete. Honestly out of scope even so: Section 12's run-control/registry/workshop HTTP service APIs, the S1-S8 orchestrator state machine, and ACORD Reference Architecture content (unlicensed since Increment 1) - see `docs/increments.md`'s Increment 9 section for the full completion-boundary note.
**Last Updated**: 1 September 2026
