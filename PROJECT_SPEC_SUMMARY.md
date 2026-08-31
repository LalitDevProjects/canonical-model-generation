# Canonical Model Generation Technical Specification Summary

## Project Overview
A platform that derives canonical domain models from regional API estates. It reads source repositories, interface definitions, and API contracts; normalizes them; clusters attributes; aligns to ACORD Reference Architecture; and proposes canonical models with coverage reports.

## Key Details
- **Language**: Python 3.12 for pipeline/agent code, JSON Schema for contracts, YAML for configuration
- **Domain**: Claims (Wave 1)
- **Regions**: US, UK, EU
- **Primary Audience**: Engineering team implementing the platform

## Major Components (from Table of Contents)

### 1. **Architecture** (Section 2)
   - Component inventory
   - Topology
   - Technology stack
   - Runtime model
   - Cross-cutting rules

### 2. **Data Contracts** (Section 3)
   - Contract catalogue
   - Identity, references, invariants
   - C5 – AttributeRecord
   - C1, C4 – SourceArtefact, CorpusManifest  
   - C6, C7, C8 – cluster, alignment, candidate
   - C11 – RunManifest, JournalEvent
   - Storage layout

### 3. **Ingestion & Normalization** (Section 4)
   - Connector interface
   - Relevance filtering
   - Type normalisation
   - XSD/WSDL handling
   - Code contract inference
   - Incremental ingestion

### 4. **Sanitisation & Egress Gate** (Section 5)
   - Classification ladder
   - Detector specification
   - Tokenisation
   - Policy decision point
   - Egress ledger
   - Blocking behaviour

### 5. **Knowledge Substrate** (Section 6)
   - Purpose
   - Chunking
   - Concept graph
   - Retrieval API

### 6. **Agent Framework** (Section 7)
   - Invocation path
   - Tool gateway
   - Validation ladder
   - Prompt templates
   - Agent specifications
   - Retry, escalation, budget
   - Model routing

### 7. **Orchestration** (Section 8)
   - Run state machine
   - Work items and fan-out
   - State machine definition
   - Checkpointing
   - Resume and re-baseline
   - Concurrency and rate limits

### 8. **Core Algorithms** (Section 9)
   - Attribute profiling
   - Blocking
   - Similarity scoring
   - Clustering
   - Conflict classification
   - ACORD alignment scoring
   - Core vs extension partitioning
   - Coverage computation
   - Naming conventions

### 9. **Mapping Specification Language** (Section 10)
   - Design goals
   - Grammar
   - Transform library
   - Static checks
   - Round-trip test generation
   - Reference interpreter

### 10. **Artefact Emission & Registry** (Section 11)
   - Emission rules
   - Extension namespace schemas
   - Logical model export
   - Versioning

### 11. **Internal Service APIs** (Section 12)
   - Conventions
   - Run control API
   - Registry API
   - Workshop and decision API
   - Error model

### 12. **Security** (Section 13)
   - Identity and access
   - Network
   - Prompt injection protection
   - Audit

### 13. **Observability & Cost Control** (Section 14)
   - Metrics
   - Tracing and logging
   - Cost control

### 14. **Configuration** (Section 15)
   - Configuration model
   - Environments
   - Feature flags

### 15. **Testing Strategy** (Section 16)
   - Golden corpus
   - Deterministic component tests
   - Agent evaluation harness
   - Regression testing
   - Re-baseline testing

### 16. **PoC Build Guide** (Section 17)
   - Objective
   - Increments
   - Sequencing rules
   - Repository layout
   - Definition of done
   - Exit criteria

### 17. **Operations** (Section 18)
   - Starting a run
   - Failure playbook
   - Re-baseline procedure
   - Retention and deletion

## Output Artefacts
1. Canonical contracts (OpenAPI 3.1 with JSON Schema)
2. Bidirectional region-to-canonical mapping specifications with generated tests
3. Tool-neutral logical model with glossary and lineage
4. Coverage and gap reports
5. Signed release manifest

## Key Constraint
**The platform proposes. Humans ratify.** No artefact reaches release without named human approver.

## Next Steps
1. Review detailed sections in specification
2. Design repository structure
3. Implement data contracts first (Section 3)
4. Build ingestion pipeline (Section 4)
5. Implement core algorithms (Section 9)
6. Build agent framework (Section 7)
7. Implement orchestration (Section 8)
8. Add APIs and testing (Sections 12, 16)
