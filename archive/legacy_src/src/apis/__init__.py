"""
Internal Service APIs (Section 12)

REST/gRPC APIs for inter-service communication within the platform.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from ..models import RunManifest, Candidate, AttributeRecord


# ============================================================================
# Run Control API (Section 12.2)
# ============================================================================

class StartRunRequest(BaseModel):
    """Request to start a run."""
    run_name: str = Field(description="Name for this run")
    corpus_manifest_id: UUID = Field(description="Input corpus")
    initiated_by: str = Field(description="User initiating run")


class RunStatusResponse(BaseModel):
    """Current status of a run."""
    run_id: UUID
    status: str
    started_at: str
    progress_percentage: float
    stages_completed: List[str]
    pending_approvals: Dict[str, str]


class ApprovalRequest(BaseModel):
    """Request approval for a checkpoint."""
    run_id: UUID
    checkpoint_type: str
    approver_role: str


class ApprovalResponse(BaseModel):
    """Approval decision response."""
    run_id: UUID
    checkpoint_type: str
    approved: bool
    approved_by: str
    notes: str = ""


# ============================================================================
# Registry API (Section 12.3)
# ============================================================================

class RegisterArtefactRequest(BaseModel):
    """Request to register an artefact."""
    artefact_type: str  # canonical_contract, mapping, logical_model, etc.
    run_id: UUID
    artefact_data: Dict[str, Any]
    version: str


class QueryArtefactRequest(BaseModel):
    """Request to query artefacts."""
    artefact_type: Optional[str] = None
    domain_area: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None


# ============================================================================
# Workshop and Decision API (Section 12.4)
# ============================================================================

class CandidateReviewRequest(BaseModel):
    """Request to review a candidate canonical model element."""
    candidate_id: UUID
    candidate: Candidate
    context: Dict[str, Any] = Field(default_factory=dict)


class CandidateDecision(BaseModel):
    """Decision on a candidate."""
    candidate_id: UUID
    decision: str  # approved, rejected, revise
    decided_by: str
    notes: str = ""
    proposed_modifications: Optional[Dict[str, Any]] = None


# ============================================================================
# Error Model (Section 12.5)
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error_code: str = Field(description="Machine-readable error code")
    error_message: str = Field(description="Human-readable message")
    details: Optional[Dict[str, Any]] = Field(default=None)
    timestamp: str = Field(description="ISO 8601 timestamp")


class ValidationError(ErrorResponse):
    """Validation error details."""
    validation_errors: List[Dict[str, Any]] = Field(
        description="List of validation failures"
    )


class APIConventions:
    """
    API conventions and standards (Section 12.1).
    
    Defines common patterns for all APIs:
    - Authentication and authorization
    - Request/response format
    - Error handling
    - Pagination
    - Rate limiting
    """
    
    # Standard response envelope
    RESPONSE_ENVELOPE = {
        "success": True,
        "data": {},  # Actual response
        "error": None,
        "timestamp": "",  # ISO 8601
        "request_id": "",  # For tracing
    }
    
    # Standard error codes
    ERROR_CODES = {
        "INVALID_REQUEST": 400,
        "UNAUTHORIZED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "CONFLICT": 409,
        "RATE_LIMITED": 429,
        "INTERNAL_ERROR": 500,
        "SERVICE_UNAVAILABLE": 503,
    }
    
    # Rate limits (per minute)
    RATE_LIMITS = {
        "default": 100,
        "run_control": 10,
        "registry": 50,
        "workshop": 5,
    }


__all__ = [
    "StartRunRequest",
    "RunStatusResponse",
    "ApprovalRequest",
    "ApprovalResponse",
    "RegisterArtefactRequest",
    "QueryArtefactRequest",
    "CandidateReviewRequest",
    "CandidateDecision",
    "ErrorResponse",
    "ValidationError",
    "APIConventions",
]
