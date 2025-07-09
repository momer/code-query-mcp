"""Dataset management module for code-query-mcp.

This module provides comprehensive dataset lifecycle management including:
- Dataset creation, forking, and deletion
- Git worktree support
- Dataset synchronization
- Validation and error handling
"""

from .dataset_models import (
    Dataset,
    DatasetType,
    SyncDirection,
    SyncOperation,
    DatasetStats,
    DatasetDiff,
    DatasetValidationError,
)
from .dataset_service import DatasetService
from .dataset_validator import DatasetValidator
from .worktree_handler import WorktreeHandler
from .dataset_sync import DatasetSynchronizer

__all__ = [
    # Models
    "Dataset",
    "DatasetType",
    "SyncDirection",
    "SyncOperation",
    "DatasetStats",
    "DatasetDiff",
    "DatasetValidationError",
    # Services
    "DatasetService",
    "DatasetValidator",
    "WorktreeHandler",
    "DatasetSynchronizer",
]