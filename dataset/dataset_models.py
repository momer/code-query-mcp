"""Domain models and DTOs for dataset management."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class DatasetType(Enum):
    """Types of datasets supported."""
    MAIN = "main"
    WORKTREE = "worktree"
    FORK = "fork"
    TEMPORARY = "temporary"


class SyncDirection(Enum):
    """Direction of dataset synchronization."""
    SOURCE_TO_TARGET = "source_to_target"
    TARGET_TO_SOURCE = "target_to_source"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class Dataset:
    """Complete dataset information."""
    dataset_id: str
    source_dir: str
    dataset_type: DatasetType
    created_at: datetime
    updated_at: datetime
    files_count: int = 0
    parent_dataset_id: Optional[str] = None
    source_branch: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_worktree(self) -> bool:
        """Check if this is a worktree dataset."""
        return self.dataset_type == DatasetType.WORKTREE
    
    def has_parent(self) -> bool:
        """Check if this dataset was forked from another."""
        return self.parent_dataset_id is not None


@dataclass
class SyncOperation:
    """Details of a sync operation."""
    source_dataset_id: str
    target_dataset_id: str
    direction: SyncDirection
    source_ref: str
    target_ref: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    files_synced: int = 0
    errors: List[str] = field(default_factory=list)
    
    def is_successful(self) -> bool:
        """Check if sync completed successfully."""
        return self.completed_at is not None and len(self.errors) == 0


@dataclass
class DatasetStats:
    """Statistics about a dataset."""
    dataset_id: str
    total_files: int
    total_size_bytes: int
    last_updated: datetime
    file_types: Dict[str, int]  # Extension -> count
    largest_files: List[tuple[str, int]]  # [(filepath, size), ...]


@dataclass
class DatasetValidationError(Exception):
    """Validation error with details."""
    field: str
    value: Any
    message: str
    
    def __str__(self):
        return f"Validation error for {self.field}='{self.value}': {self.message}"


@dataclass
class DatasetDiff:
    """Differences between two datasets."""
    added_files: List[str]
    modified_files: List[str]
    deleted_files: List[str]
    
    @property
    def total_changes(self) -> int:
        return len(self.added_files) + len(self.modified_files) + len(self.deleted_files)
    
    def is_empty(self) -> bool:
        return self.total_changes == 0