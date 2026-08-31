"""
Data Models and Contracts

This module defines the core data contracts (C1-C11) as specified in Section 3
of the technical specification. These Pydantic models form the foundation of
all data flowing through the platform.

Contract Inventory:
- C1: SourceArtefact - External input data from regions
- C4: CorpusManifest - Metadata about corpus/collection of sources
- C5: AttributeRecord - Normalized representation of attributes
- C6: ConceptCluster - Cluster of semantically related attributes
- C7: Alignment - Mapping between attributes and ACORD concepts
- C8: Candidate - Proposed canonical model element
- C11: RunManifest - Execution run tracking
- C11: JournalEvent - Event log entries for run
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Region(str, Enum):
    """Supported regional API estates."""
    US = "us"
    UK = "uk"
    EU = "eu"


class DomainArea(str, Enum):
    """Business domains in scope."""
    CLAIMS = "claims"  # Wave 1
    PARTY = "party"
    ADDRESS = "address"
    MONEY = "money"


class SourceType(str, Enum):
    """Input source types supported by ingestion."""
    WSDL = "wsdl"
    XSD = "xsd"
    OPENAPI = "openapi"
    JSON_SCHEMA = "json_schema"
    CUSTOM_CONTRACT = "custom_contract"
    CODE_ANNOTATION = "code_annotation"


class ProcessingStatus(str, Enum):
    """Status of processing in the pipeline."""
    INGESTED = "ingested"
    NORMALIZED = "normalized"
    PROFILED = "profiled"
    CLUSTERED = "clustered"
    ALIGNED = "aligned"
    CANDIDATE_GENERATED = "candidate_generated"
    VALIDATED = "validated"
    APPROVED = "approved"
    RELEASED = "released"


class BlockingReason(str, Enum):
    """Reasons for blocking attributes from processing."""
    PII = "pii"
    PROPRIETARY = "proprietary"
    DEPRECATED = "deprecated"
    OUT_OF_SCOPE = "out_of_scope"
    TECHNICAL_DEBT = "technical_debt"


class SanitisationLevel(str, Enum):
    """Classification ladder for data sensitivity."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


# ============================================================================
# C1: SourceArtefact - External input sources
# ============================================================================

class SourceArtefact(BaseModel):
    """
    C1 - SourceArtefact: External artifact from region API estate.
    
    Represents an input source (schema, contract, specification) from one
    of the regional API estates. Tracks origin, format, and content.
    
    Invariant: Identity is (region, source_type, external_id)
    """
    
    id: UUID = Field(description="Unique identifier for this source")
    region: Region = Field(description="Source region: US, UK, or EU")
    source_type: SourceType = Field(description="Type of source format")
    external_id: str = Field(description="External identifier in source system")
    
    name: str = Field(description="Human-readable name")
    description: Optional[str] = Field(default=None)
    
    domain_area: DomainArea = Field(description="Business domain this covers")
    version: str = Field(description="Source version identifier")
    
    # Content and origin
    url: Optional[HttpUrl] = Field(default=None, description="URL to source")
    content_hash: str = Field(description="SHA256 hash of source content")
    content_preview: str = Field(description="First 1000 chars of content")
    
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ingested_by: str = Field(description="User/system that performed ingestion")
    
    # Traceability
    tags: Set[str] = Field(default_factory=set)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


# ============================================================================
# C4: CorpusManifest - Collection metadata
# ============================================================================

class CorpusManifest(BaseModel):
    """
    C4 - CorpusManifest: Metadata about a corpus of source artifacts.
    
    Aggregates multiple SourceArtefacts into a named collection with
    lineage and attestation information.
    
    Invariant: Immutable once finalized. All component artefacts must have
    content_hash verified before manifest finalization.
    """
    
    id: UUID = Field(description="Unique manifest identifier")
    corpus_name: str = Field(description="Human name for this corpus")
    
    domain_area: DomainArea = Field(description="Primary domain")
    regions: List[Region] = Field(description="Regions covered")
    
    # Composition
    source_artefact_ids: List[UUID] = Field(description="Component source IDs")
    source_count: int = Field(description="Total sources in corpus")
    
    # Temporal
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finalized_at: Optional[datetime] = Field(default=None)
    
    # Provenance and ratification
    created_by: str = Field(description="User who created manifest")
    approved_by: Optional[str] = Field(default=None, description="Approver if ratified")
    
    # Attestation
    is_finalized: bool = Field(default=False, description="Ready for processing")
    manifest_hash: str = Field(description="Hash of manifest contents")
    
    # Metadata
    description: Optional[str] = Field(default=None)
    tags: Set[str] = Field(default_factory=set)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


# ============================================================================
# C5: AttributeRecord - Normalized attribute representation
# ============================================================================

class DataType(str, Enum):
    """Normalized data type classifications."""
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    BINARY = "binary"
    OBJECT = "object"
    ARRAY = "array"
    UNKNOWN = "unknown"


class AttributeRecord(BaseModel):
    """
    C5 - AttributeRecord: Normalized attribute representation.
    
    Core entity representing a single attribute from source materials,
    normalized into canonical form. Tracks type, constraints, and lineage.
    
    Invariant: Single origin is (source_artefact_id, xpath_or_reference).
    No attribute exists without provenance.
    """
    
    id: UUID = Field(description="Unique attribute identifier")
    
    # Identification and origin
    source_artefact_id: UUID = Field(description="Source artifact reference")
    region: Region = Field(description="Region this attribute is from")
    domain_area: DomainArea = Field(description="Domain this attribute belongs to")
    
    # Location in source
    xpath_or_reference: str = Field(
        description="XPath for XML, JSON path for JSON, or reference"
    )
    source_path_alternate: Optional[List[str]] = Field(
        default=None, description="Alternative paths in same source"
    )
    
    # Semantics
    name: str = Field(description="Attribute name in source")
    canonical_name: Optional[str] = Field(default=None, description="Proposed canonical name")
    description: Optional[str] = Field(default=None)
    
    # Type information
    data_type: DataType = Field(description="Normalized type")
    data_type_original: str = Field(description="Original type in source")
    
    # Constraints and cardinality
    required: bool = Field(default=True)
    min_length: Optional[int] = Field(default=None)
    max_length: Optional[int] = Field(default=None)
    min_value: Optional[float] = Field(default=None)
    max_value: Optional[float] = Field(default=None)
    pattern_regex: Optional[str] = Field(default=None)
    allowed_values: Optional[List[Any]] = Field(default=None)
    
    # Cardinality
    min_occurs: int = Field(default=1)
    max_occurs: Optional[int] = Field(default=1)  # None = unbounded
    
    # Context and semantic hints
    parent_element: Optional[str] = Field(default=None, description="Parent in hierarchy")
    semantic_hints: Set[str] = Field(default_factory=set, description="Tags: PII, currency, date, etc.")
    
    # Processing and blocking
    is_blocked: bool = Field(default=False)
    blocking_reason: Optional[BlockingReason] = Field(default=None)
    
    sanitisation_level: SanitisationLevel = Field(default=SanitisationLevel.INTERNAL)
    
    # Lineage and tracking
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.INGESTED)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Additional metadata
    examples: List[str] = Field(default_factory=list, description="Sample values from source")
    frequency: Optional[Dict[str, int]] = Field(
        default=None, description="Value frequency distribution if known"
    )
    
    tags: Set[str] = Field(default_factory=set)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


# ============================================================================
# C6-C8: Clustering and Alignment intermediate results
# ============================================================================

class ConceptCluster(BaseModel):
    """
    C6 - ConceptCluster: Cluster of semantically related attributes.
    
    Groups attributes that appear to represent the same concept across
    regions and sources. Result of clustering algorithm.
    """
    
    id: UUID = Field(description="Cluster identifier")
    cluster_name: str = Field(description="Proposed concept name")
    
    # Composition
    attribute_ids: List[UUID] = Field(description="Attribute IDs in cluster")
    region_coverage: Dict[Region, int] = Field(description="Attributes per region")
    
    # Scoring
    cohesion_score: float = Field(ge=0.0, le=1.0, description="Internal similarity")
    confidence: float = Field(ge=0.0, le=1.0, description="Clustering confidence")
    
    # Representative information
    representative_attributes: List[UUID] = Field(
        description="Most representative members"
    )
    
    # Details
    description: Optional[str] = Field(default=None)
    semantic_keywords: Set[str] = Field(default_factory=set)
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


class Alignment(BaseModel):
    """
    C7 - Alignment: Mapping between cluster and ACORD reference concept.
    
    Records alignment of discovered cluster to ACORD Reference Architecture.
    """
    
    id: UUID = Field(description="Alignment identifier")
    cluster_id: UUID = Field(description="Cluster being aligned")
    
    # ACORD Reference details
    acord_entity: str = Field(description="ACORD entity path")
    acord_attribute: str = Field(description="ACORD attribute name")
    
    # Scoring
    alignment_score: float = Field(ge=0.0, le=1.0)
    justification: str = Field(description="Why this alignment was chosen")
    
    # Alternatives considered
    alternative_alignments: List[tuple[str, float]] = Field(
        default_factory=list, description="Other options and scores"
    )
    
    # Decision
    approved: bool = Field(default=False)
    approved_by: Optional[str] = Field(default=None)
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


class Candidate(BaseModel):
    """
    C8 - Candidate: Proposed canonical model element.
    
    Synthesized from cluster and alignment, represents a proposed element
    for the canonical model. Subject to human ratification.
    """
    
    id: UUID = Field(description="Candidate identifier")
    cluster_id: UUID = Field(description="Source cluster")
    alignment_id: Optional[UUID] = Field(default=None, description="ACORD alignment if any")
    
    # Proposed canonical form
    canonical_name: str = Field(description="Proposed canonical name")
    canonical_description: str = Field(description="Proposed description")
    canonical_data_type: DataType = Field(description="Proposed type")
    
    # Properties
    required: bool = Field(default=True)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    
    # Coverage
    coverage_percentage: float = Field(ge=0.0, le=100.0)
    covered_attributes: List[UUID] = Field(description="Attributes this covers")
    uncovered_attributes: List[UUID] = Field(description="Attributes NOT covered")
    
    # Extensions needed
    requires_extension_namespace: bool = Field(default=False)
    extension_definition: Optional[str] = Field(default=None)
    
    # Decision state
    ratification_status: str = Field(default="proposed")  # proposed, approved, rejected, revised
    ratified_by: Optional[str] = Field(default=None)
    ratification_notes: Optional[str] = Field(default=None)
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


# ============================================================================
# C11: RunManifest and JournalEvent - Execution tracking
# ============================================================================

class RunStatus(str, Enum):
    """Status of a processing run."""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CHECKPOINTED = "checkpointed"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunManifest(BaseModel):
    """
    C11 - RunManifest: Execution run tracking.
    
    Records a complete run through the pipeline, including all inputs,
    processing steps, intermediate states, and outputs.
    
    Invariant: Immutable once completed/failed.
    """
    
    id: UUID = Field(description="Unique run identifier")
    run_name: str = Field(description="Human-readable run name")
    
    # Configuration
    domain_area: DomainArea = Field(description="Domain being processed")
    corpus_manifest_id: UUID = Field(description="Input corpus")
    
    # Temporal
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    
    # Execution tracking
    status: RunStatus = Field(default=RunStatus.QUEUED)
    initiated_by: str = Field(description="User who started run")
    
    # Processing stages completed
    stages_completed: Set[str] = Field(
        default_factory=set,
        description="Completed pipeline stages"
    )
    
    # Intermediate results
    source_count: int = Field(description="Sources processed")
    attribute_count: int = Field(description="Attributes extracted")
    cluster_count: int = Field(description="Clusters generated")
    candidate_count: int = Field(description="Candidates proposed")
    
    # Approvals and checkpoints
    checkpoints_passed: List[str] = Field(
        default_factory=list, description="Checkpoints successfully passed"
    )
    pending_approvals: Dict[str, str] = Field(
        default_factory=dict, description="Approval stage -> approver required"
    )
    
    # Output artefacts
    output_artefacts: Dict[str, str] = Field(
        default_factory=dict, 
        description="Generated artefact type -> registry ID"
    )
    
    # Error and logging
    error_log: List[str] = Field(default_factory=list)
    warning_log: List[str] = Field(default_factory=list)
    
    # Cost tracking
    estimated_cost: Optional[float] = Field(default=None, description="Estimated API costs")
    actual_cost: Optional[float] = Field(default=None)
    
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(use_enum_values=True)


class JournalEventType(str, Enum):
    """Types of journal events."""
    RUN_STARTED = "run_started"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    CHECKPOINT_REACHED = "checkpoint_reached"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"
    WARNING = "warning"
    METRIC = "metric"
    OUTPUT_GENERATED = "output_generated"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class JournalEvent(BaseModel):
    """
    C11 - JournalEvent: Event log entry for a run.
    
    Immutable event log tracking all significant moments in execution.
    """
    
    id: UUID = Field(description="Event identifier")
    run_id: UUID = Field(description="Associated run")
    
    event_type: JournalEventType = Field(description="Type of event")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Event details
    stage: Optional[str] = Field(default=None, description="Pipeline stage")
    message: str = Field(description="Event message")
    
    # Context
    actor: Optional[str] = Field(default=None, description="User or system performing action")
    
    # Structured data about event
    properties: Dict[str, Any] = Field(default_factory=dict)
    
    # Error details if applicable
    error_code: Optional[str] = Field(default=None)
    error_details: Optional[Dict[str, Any]] = Field(default=None)
    
    model_config = ConfigDict(use_enum_values=True)


# Index of all contracts
__all__ = [
    # Enums
    "Region",
    "DomainArea", 
    "SourceType",
    "ProcessingStatus",
    "BlockingReason",
    "SanitisationLevel",
    "DataType",
    "RunStatus",
    "JournalEventType",
    # Contracts
    "SourceArtefact",
    "CorpusManifest",
    "AttributeRecord",
    "ConceptCluster",
    "Alignment",
    "Candidate",
    "RunManifest",
    "JournalEvent",
]
