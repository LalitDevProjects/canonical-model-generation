"""
Orchestration Engine (Section 8)

State machine-based orchestration of the canonical model generation pipeline.
Manages runs, work items, checkpoints, and human approval gates.
"""

from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from ..models import (
    RunManifest,
    RunStatus,
    JournalEvent,
    JournalEventType,
    CorpusManifest,
    DomainArea,
)


class PipelineStage(str, Enum):
    """Pipeline processing stages (Section 8.2)."""
    INGESTION = "ingestion"
    NORMALIZATION = "normalization"
    PROFILING = "profiling"
    CLUSTERING = "clustering"
    ALIGNMENT = "alignment"
    CANDIDATE_GENERATION = "candidate_generation"
    VALIDATION = "validation"
    SANITISATION = "sanitisation"
    GENERATION = "generation"
    RATIFICATION = "ratification"


class CheckpointType(str, Enum):
    """Types of checkpoints requiring human decision (Section 8.1)."""
    INGESTION_COMPLETE = "ingestion_complete"
    CLUSTER_REVIEW = "cluster_review"
    ACORD_ALIGNMENT = "acord_alignment"
    CANDIDATE_APPROVAL = "candidate_approval"
    FINAL_RELEASE = "final_release"


class WorkItem:
    """
    Work item for parallel processing (Section 8.2).
    
    Represents a unit of work that can be processed independently,
    enabling fan-out parallelization.
    """
    
    def __init__(
        self,
        item_id: UUID,
        stage: PipelineStage,
        payload: Dict[str, Any],
        dependencies: Optional[List[UUID]] = None,
    ):
        """
        Initialize work item.
        
        Args:
            item_id: Unique identifier
            stage: Pipeline stage for this work
            payload: Data for processing
            dependencies: IDs of work items that must complete first
        """
        self.item_id = item_id
        self.stage = stage
        self.payload = payload
        self.dependencies = dependencies or []
        self.status = "pending"
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[Dict[str, Any]] = None


class RunStateMachine:
    """
    State machine for run orchestration (Section 8.1, 8.3).
    
    Manages transitions between pipeline stages with checkpoint gates.
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        RunStatus.QUEUED: [RunStatus.RUNNING],
        RunStatus.RUNNING: [
            RunStatus.PAUSED,
            RunStatus.CHECKPOINTED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        ],
        RunStatus.CHECKPOINTED: [
            RunStatus.AWAITING_APPROVAL,
            RunStatus.PAUSED,
        ],
        RunStatus.AWAITING_APPROVAL: [
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ],
        RunStatus.PAUSED: [RunStatus.RUNNING, RunStatus.CANCELLED],
        RunStatus.COMPLETED: [],
        RunStatus.FAILED: [RunStatus.RUNNING],  # Resume
        RunStatus.CANCELLED: [],
    }
    
    def __init__(self, run_manifest: RunManifest):
        """
        Initialize state machine for a run.
        
        Args:
            run_manifest: The run being orchestrated
        """
        self.run = run_manifest
        self.journal: List[JournalEvent] = []
    
    def can_transition(self, new_status: RunStatus) -> bool:
        """Check if transition is valid."""
        current = self.run.status
        valid = self.VALID_TRANSITIONS.get(current, [])
        return new_status in valid
    
    def transition(
        self,
        new_status: RunStatus,
        actor: str,
        message: str = "",
    ) -> bool:
        """
        Attempt state transition.
        
        Args:
            new_status: Target status
            actor: User/system initiating transition
            message: Description of transition
            
        Returns:
            True if transition succeeded
        """
        if not self.can_transition(new_status):
            return False
        
        old_status = self.run.status
        self.run.status = new_status
        
        # Record event
        event = JournalEvent(
            id=uuid4(),
            run_id=self.run.id,
            event_type=JournalEventType.STAGE_STARTED,
            message=f"Transitioned from {old_status} to {new_status}: {message}",
            actor=actor,
        )
        self.journal.append(event)
        
        return True
    
    def checkpoint(self, checkpoint_type: CheckpointType, actor: str) -> bool:
        """
        Reach a checkpoint requiring human approval.
        
        Args:
            checkpoint_type: Type of checkpoint
            actor: User reaching checkpoint
            
        Returns:
            True if checkpoint recorded
        """
        if self.run.status != RunStatus.RUNNING:
            return False
        
        self.run.checkpoints_passed.append(checkpoint_type.value)
        
        # Record event
        event = JournalEvent(
            id=uuid4(),
            run_id=self.run.id,
            event_type=JournalEventType.CHECKPOINT_REACHED,
            stage=checkpoint_type.value,
            message=f"Checkpoint reached: {checkpoint_type.value}",
            actor=actor,
        )
        self.journal.append(event)
        
        return self.transition(RunStatus.CHECKPOINTED, actor)
    
    def request_approval(
        self,
        checkpoint_type: CheckpointType,
        approver_required: str,
        reason: str = "",
    ) -> None:
        """
        Request approval for a checkpoint.
        
        Args:
            checkpoint_type: Checkpoint type
            approver_required: Role/person required to approve
            reason: Why approval is needed
        """
        key = checkpoint_type.value
        self.run.pending_approvals[key] = approver_required
        
        event = JournalEvent(
            id=uuid4(),
            run_id=self.run.id,
            event_type=JournalEventType.APPROVAL_REQUESTED,
            stage=key,
            message=f"Approval requested: {reason}",
            properties={"approver_required": approver_required},
        )
        self.journal.append(event)
    
    def approve(
        self,
        checkpoint_type: CheckpointType,
        approver: str,
        notes: str = "",
    ) -> bool:
        """
        Approve a pending checkpoint.
        
        Args:
            checkpoint_type: Checkpoint being approved
            approver: User approving
            notes: Approval notes
            
        Returns:
            True if approval recorded
        """
        key = checkpoint_type.value
        if key not in self.run.pending_approvals:
            return False
        
        del self.run.pending_approvals[key]
        
        event = JournalEvent(
            id=uuid4(),
            run_id=self.run.id,
            event_type=JournalEventType.APPROVED,
            stage=key,
            message=f"Checkpoint approved with notes: {notes}",
            actor=approver,
        )
        self.journal.append(event)
        
        return self.transition(RunStatus.RUNNING, approver)


class OrchestrationEngine:
    """
    Main orchestration engine.
    
    Coordinates pipeline execution, manages state, handles checkpoints,
    and coordinates parallel work items (Section 8).
    """
    
    def __init__(self):
        """Initialize orchestration engine."""
        self.active_runs: Dict[UUID, RunManifest] = {}
        self.state_machines: Dict[UUID, RunStateMachine] = {}
        self.work_queue: List[WorkItem] = []
        self.completed_work: Dict[UUID, WorkItem] = {}
    
    def start_run(
        self,
        run_manifest: RunManifest,
        corpus_manifest: CorpusManifest,
    ) -> bool:
        """
        Start a new run.
        
        Args:
            run_manifest: The run configuration
            corpus_manifest: Input corpus
            
        Returns:
            True if run started successfully
        """
        if run_manifest.id in self.active_runs:
            return False
        
        # Initialize state machine
        state_machine = RunStateMachine(run_manifest)
        
        # Transition to RUNNING
        if not state_machine.transition(RunStatus.RUNNING, run_manifest.initiated_by):
            return False
        
        # Store
        self.active_runs[run_manifest.id] = run_manifest
        self.state_machines[run_manifest.id] = state_machine
        
        return True
    
    def create_work_items(
        self,
        run_id: UUID,
        stage: PipelineStage,
        payloads: List[Dict[str, Any]],
    ) -> List[UUID]:
        """
        Create work items for parallel processing (Section 8.2).
        
        Args:
            run_id: Associated run
            stage: Pipeline stage
            payloads: Work item payloads
            
        Returns:
            List of work item IDs
        """
        item_ids = []
        
        for payload in payloads:
            item = WorkItem(
                item_id=uuid4(),
                stage=stage,
                payload=payload,
            )
            self.work_queue.append(item)
            item_ids.append(item.item_id)
        
        return item_ids
    
    def complete_work_item(
        self,
        work_item_id: UUID,
        result: Dict[str, Any],
    ) -> bool:
        """
        Mark work item as completed.
        
        Args:
            work_item_id: Work item ID
            result: Result data
            
        Returns:
            True if marked successfully
        """
        # Find and remove from queue
        item = None
        for i, work_item in enumerate(self.work_queue):
            if work_item.item_id == work_item_id:
                item = self.work_queue.pop(i)
                break
        
        if not item:
            return False
        
        item.status = "completed"
        item.completed_at = datetime.utcnow()
        item.result = result
        
        self.completed_work[work_item_id] = item
        return True
    
    def checkpoint(
        self,
        run_id: UUID,
        checkpoint_type: CheckpointType,
        actor: str,
    ) -> bool:
        """
        Reach a checkpoint.
        
        Args:
            run_id: Run ID
            checkpoint_type: Type of checkpoint
            actor: User reaching checkpoint
            
        Returns:
            True if checkpoint recorded
        """
        state_machine = self.state_machines.get(run_id)
        if not state_machine:
            return False
        
        return state_machine.checkpoint(checkpoint_type, actor)
    
    def complete_run(
        self,
        run_id: UUID,
        completed_by: str,
    ) -> bool:
        """
        Mark run as completed.
        
        Args:
            run_id: Run ID
            completed_by: User completing
            
        Returns:
            True if run completed
        """
        run = self.active_runs.get(run_id)
        state_machine = self.state_machines.get(run_id)
        
        if not run or not state_machine:
            return False
        
        run.completed_at = datetime.utcnow()
        return state_machine.transition(RunStatus.COMPLETED, completed_by)
    
    def fail_run(
        self,
        run_id: UUID,
        error_message: str,
        failed_by: str = "system",
    ) -> bool:
        """
        Mark run as failed.
        
        Args:
            run_id: Run ID
            error_message: Error description
            failed_by: User/system marking as failed
            
        Returns:
            True if run failed
        """
        run = self.active_runs.get(run_id)
        state_machine = self.state_machines.get(run_id)
        
        if not run or not state_machine:
            return False
        
        run.error_log.append(error_message)
        run.completed_at = datetime.utcnow()
        return state_machine.transition(RunStatus.FAILED, failed_by, error_message)
    
    def get_run_journal(self, run_id: UUID) -> List[JournalEvent]:
        """Get event journal for a run."""
        state_machine = self.state_machines.get(run_id)
        return state_machine.journal if state_machine else []


__all__ = [
    "PipelineStage",
    "CheckpointType",
    "WorkItem",
    "RunStateMachine",
    "OrchestrationEngine",
]
