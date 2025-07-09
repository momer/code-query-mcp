"""Domain models for documentation jobs."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid


class JobStatus(Enum):
    """Status states for documentation jobs."""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DocumentationJob:
    """
    Represents a documentation job that processes multiple files.
    
    This model tracks the overall job state and enables:
    - Crash recovery by tracking progress
    - Job cancellation with partial results
    - Progress reporting to users
    """
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dataset_name: str = ""
    project_root: str = ""
    status: JobStatus = JobStatus.CREATED
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Additional metadata for resumption
    file_filters: Optional[List[str]] = None  # Glob patterns used for discovery
    options: Dict[str, Any] = field(default_factory=dict)  # Model, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "job_id": self.job_id,
            "dataset_name": self.dataset_name,
            "project_root": self.project_root,
            "status": self.status.value,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "failed_files": self.failed_files,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "file_filters": self.file_filters,
            "options": self.options
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentationJob":
        """Create from dictionary representation."""
        job = cls(
            job_id=data["job_id"],
            dataset_name=data["dataset_name"],
            project_root=data["project_root"],
            status=JobStatus(data["status"]),
            total_files=data["total_files"],
            processed_files=data["processed_files"],
            failed_files=data.get("failed_files", 0),
            error_message=data.get("error_message"),
            file_filters=data.get("file_filters"),
            options=data.get("options", {})
        )
        
        # Parse datetime fields
        job.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("started_at"):
            job.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            job.completed_at = datetime.fromisoformat(data["completed_at"])
            
        return job
    
    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
    
    @property
    def can_resume(self) -> bool:
        """Check if job can be resumed."""
        return self.status in (JobStatus.CREATED, JobStatus.RUNNING)
    
    def progress_percentage(self) -> float:
        """Calculate progress as percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.processed_files / self.total_files) * 100


@dataclass 
class ProcessedFile:
    """Tracks individual file processing within a job."""
    job_id: str
    filepath: str
    processed_at: datetime
    success: bool
    error_message: Optional[str] = None
    huey_task_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "job_id": self.job_id,
            "filepath": self.filepath,
            "processed_at": self.processed_at.isoformat(),
            "success": self.success,
            "error_message": self.error_message,
            "huey_task_id": self.huey_task_id
        }


@dataclass
class JobProgress:
    """Progress update for a running job."""
    job_id: str
    processed_files: int
    total_files: int
    current_file: Optional[str] = None
    percentage: float = 0.0
    estimated_remaining_seconds: Optional[int] = None
    
    @classmethod
    def from_job(cls, job: DocumentationJob, current_file: Optional[str] = None) -> "JobProgress":
        """Create progress from job state."""
        return cls(
            job_id=job.job_id,
            processed_files=job.processed_files,
            total_files=job.total_files,
            current_file=current_file,
            percentage=job.progress_percentage()
        )