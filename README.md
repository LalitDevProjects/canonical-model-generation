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

**Increments 1 through 3 are complete.** Increment 1 ("Skeleton and
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
structurally. See `docs/contracts.md` and `docs/increments.md`.

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
  prompts/{agent}/      Versioned agent prompt templates (Increment 6)
  agents/               Agent runtime: tool gateway, model gateway, validation ladder (Increment 6)
  tools/                 Tool gateway implementations (Increment 6)
  connectors/           Git/Confluence connectors, relevance filtering, corpus manifest (Increment 2 - built)
  parsers/               OpenAPI/WSDL/XSD/Avro parsers, type normalisation (Increment 3 - built; code_inference.py deferred)
  gate/                  Sanitisation ladder, tokenisation, egress ledger (Increment 4)
  substrate/             Chunking, embeddings, vector + concept graph, substrate-api (Increment 5)
  pipeline/               Orchestration: run store persistence (Increment 2 - started), state machine (later)
  algorithms/            Attribute profiling (Increment 3 - started); blocking, similarity, clustering, ACORD alignment, coverage (Increments 7-8)
  mapping/               Mapping DSL: grammar, transform library, round-trip tests (Increment 9)
  emit/                   Schema/OpenAPI emitters, logical model export, registry (Increment 9)
  api/                    Internal service APIs (run control, registry, workshop)
  golden/                Golden corpus, built incrementally (Increments 2-3 - started; see golden/README.md)
  eval/                  Agent evaluation harness (Increments 6-7)
  infra/                 docker-compose.yml (local Postgres + pgvector)
  docs/                   Detailed documentation, updated alongside contract/agent changes
  tests/
    algorithms/            Profiling tests
    connectors/            Connector, relevance-filter, manifest, and golden-corpus e2e tests
    contracts/            Schema + generated-model fixture and invariant tests
    fixtures/              Per-contract positive/negative fixtures, invariant bundles
    parsers/               Parser, type-normalisation, and router tests
    pipeline/              Run-store tests
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
- Docker Desktop (optional at Increment 1 - only needed once `infra/docker-compose.yml` is actually used, from Increment 5 onward)

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
pytest --cov=generated --cov=contracts --cov=config --cov=connectors --cov=pipeline --cov=parsers --cov=algorithms --cov-report=term-missing

# Run just the contract/fixture tests
pytest tests/contracts/

# Run just the Increment 2 acceptance test (real connectors over the golden corpus)
pytest tests/connectors/test_golden_corpus_e2e.py

# Run just the Increment 3 acceptance test (the spec's own worked xsd:choice test, and profiling)
pytest tests/parsers/test_xsd.py tests/algorithms/
```

### Development

```bash
mypy --strict generated contracts config connectors pipeline parsers algorithms tests
black contracts/ config/ connectors/ pipeline/ parsers/ algorithms/ tests/ scripts/
isort contracts/ config/ connectors/ pipeline/ parsers/ algorithms/ tests/ scripts/
```

## Configuration

Configuration is layered: platform defaults (`config/platform.yaml`) under
environment variable overrides (`CMGP_` prefix). See `config/settings.py`
and `docs/contracts.md` for details.

Key configuration areas:
- Model tier routing (provider-abstracted; no concrete LLM provider is
  named anywhere in configuration or code - see Section 13/D3)
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

**Status**: Draft for Technical Review (v0.1) - Increment 1 of 9 (PoC Build Guide, Section 17) complete
**Last Updated**: 31 August 2026
