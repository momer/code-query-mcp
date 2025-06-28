# PR 5: Extract Dataset Service with Lifecycle Management

## Overview
This PR extracts dataset management functionality into a dedicated service with proper lifecycle management. It consolidates all dataset operations, provides clean APIs for dataset creation, forking, synchronization, and deletion, and supports Git worktree workflows.

**Size**: Medium | **Risk**: Low | **Value**: Medium

## Critical Updates Based on Review
1. **Removed bidirectional sync** - Requires complex 3-way merge logic not in scope
2. **Added transaction support** - All multi-step operations must be atomic
3. **Efficient statistics** - Delegate to storage backend to avoid N+1 queries
4. **Content hash for diffs** - Use SHA-256 hashes instead of timestamps
5. **Proper DTO handling** - Deep copy DTOs before modification

## Dependencies
- PR 2 must be completed (needs StorageBackend interface and DTOs)
- This PR blocks PR 6 (Application Layer needs DatasetService)
- This PR blocks PR 8 (Configuration Service needs dataset operations)

## Objectives
1. Extract all dataset operations into a dedicated service
2. Implement proper lifecycle management (create, fork, sync, delete)
3. Support Git worktree operations cleanly
4. Add comprehensive dataset validation
5. Provide clear APIs for dataset querying and manipulation

## Implementation Steps

### Step 1: Create Directory Structure
```
dataset/
├── __init__.py               # Export main classes
├── dataset_service.py        # Main dataset lifecycle management
├── dataset_sync.py           # Synchronization logic between datasets
├── worktree_handler.py       # Git worktree operations
├── dataset_models.py         # Domain models and DTOs
└── dataset_validator.py      # Validation logic
```

### Step 2: Define Domain Models
**File**: `dataset/dataset_models.py`
- Dataset DTOs with full metadata
- Sync operation models
- Validation rules
- Error types

### Step 3: Implement Dataset Service
**File**: `dataset/dataset_service.py`
- Clean API for all dataset operations
- Dependency injection for storage and git
- Transaction support for multi-step operations
- Proper error handling and recovery

### Step 4: Extract Synchronization Logic
**File**: `dataset/dataset_sync.py`
- Move sync logic from sqlite_storage.py
- Improve change detection algorithm
- Support bidirectional sync
- Handle conflict resolution

### Step 5: Implement Worktree Handler
**File**: `dataset/worktree_handler.py`
- Detect worktree configurations
- Manage worktree-specific datasets
- Handle branch switching
- Clean up orphaned datasets

### Step 6: Add Dataset Validator
**File**: `dataset/dataset_validator.py`
- Validate dataset names
- Check source directories
- Verify Git repository state
- Ensure consistency rules

## Detailed Implementation

### dataset/dataset_models.py
```python
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
```

### dataset/dataset_service.py
```python
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from .dataset_models import (
    Dataset, DatasetType, SyncOperation, DatasetStats, 
    DatasetDiff, DatasetValidationError
)
from .dataset_sync import DatasetSynchronizer
from .worktree_handler import WorktreeHandler
from .dataset_validator import DatasetValidator
from storage.backend import StorageBackend
from storage.models import DatasetMetadata, FileDocumentation
from helpers.git_helper import GitHelper

logger = logging.getLogger(__name__)

class DatasetService:
    """
    Manages dataset lifecycle with dependency injection.
    """
    
    def __init__(self, 
                 storage_backend: StorageBackend,
                 git_helper: Optional[GitHelper] = None,
                 validator: Optional[DatasetValidator] = None):
        """
        Initialize dataset service with dependencies.
        
        Args:
            storage_backend: Storage backend for persistence
            git_helper: Git operations helper
            validator: Dataset validation logic
        """
        self.storage = storage_backend
        self.git = git_helper or GitHelper()
        self.validator = validator or DatasetValidator()
        self.synchronizer = DatasetSynchronizer(self.storage)
        self.worktree_handler = WorktreeHandler(self.git)
    
    def create_dataset(self, 
                      dataset_name: str, 
                      source_dir: str,
                      dataset_type: DatasetType = DatasetType.MAIN,
                      parent_id: Optional[str] = None) -> Dataset:
        """
        Create a new dataset with validation.
        
        Args:
            dataset_name: Unique name for the dataset
            source_dir: Directory to index
            dataset_type: Type of dataset
            parent_id: Parent dataset if forked
            
        Returns:
            Created dataset
            
        Raises:
            DatasetValidationError: If validation fails
        """
        # Validate inputs
        self.validator.validate_dataset_name(dataset_name)
        self.validator.validate_source_directory(source_dir)
        
        # Check if dataset already exists
        existing = self.get_dataset(dataset_name)
        if existing:
            raise DatasetValidationError("dataset_name", dataset_name, "Dataset already exists")
        
        # Detect if this is a worktree
        if dataset_type == DatasetType.MAIN and self.worktree_handler.is_worktree(source_dir):
            dataset_type = DatasetType.WORKTREE
            branch = self.worktree_handler.get_worktree_branch(source_dir)
        else:
            branch = None
        
        # Create dataset in storage
        success = self.storage.create_dataset(
            dataset_id=dataset_name,
            source_dir=source_dir,
            dataset_type=dataset_type.value,
            parent_id=parent_id,
            source_branch=branch
        )
        
        if not success:
            raise RuntimeError(f"Failed to create dataset {dataset_name}")
        
        # Return created dataset
        metadata = self.storage.get_dataset_metadata(dataset_name)
        return self._metadata_to_dataset(metadata)
    
    def get_dataset(self, dataset_name: str) -> Optional[Dataset]:
        """
        Retrieve dataset by name.
        
        Args:
            dataset_name: Dataset identifier
            
        Returns:
            Dataset if found, None otherwise
        """
        metadata = self.storage.get_dataset_metadata(dataset_name)
        if not metadata:
            return None
        return self._metadata_to_dataset(metadata)
    
    def list_datasets(self, 
                     dataset_type: Optional[DatasetType] = None,
                     parent_id: Optional[str] = None) -> List[Dataset]:
        """
        List datasets with optional filtering.
        
        Args:
            dataset_type: Filter by type
            parent_id: Filter by parent
            
        Returns:
            List of matching datasets
        """
        all_metadata = self.storage.list_datasets()
        datasets = [self._metadata_to_dataset(m) for m in all_metadata]
        
        # Apply filters
        if dataset_type:
            datasets = [d for d in datasets if d.dataset_type == dataset_type]
        
        if parent_id:
            datasets = [d for d in datasets if d.parent_dataset_id == parent_id]
        
        return datasets
    
    def fork_dataset(self, 
                    source_dataset: str,
                    target_dataset: str,
                    target_dir: Optional[str] = None) -> Dataset:
        """
        Fork a dataset for branching or experimentation.
        
        Args:
            source_dataset: Dataset to fork from
            target_dataset: Name for forked dataset
            target_dir: Optional different source directory
            
        Returns:
            Forked dataset
            
        Raises:
            DatasetValidationError: If validation fails
            ValueError: If source dataset not found
        """
        # Validate source exists
        source = self.get_dataset(source_dataset)
        if not source:
            raise ValueError(f"Source dataset '{source_dataset}' not found")
        
        # Use source dir if not specified
        if not target_dir:
            target_dir = source.source_dir
        
        # Use transaction for atomicity
        with self.storage.transaction() as txn_storage:
            try:
                # Create forked dataset within transaction
                forked = self._create_dataset_transactional(
                    storage=txn_storage,
                    dataset_name=target_dataset,
                    source_dir=target_dir,
                    dataset_type=DatasetType.FORK,
                    parent_id=source_dataset
                )
                
                # Copy all file documentation within same transaction
                logger.info(f"Copying documentation from {source_dataset} to {target_dataset}")
                synchronizer = DatasetSynchronizer(txn_storage)
                copied = synchronizer.copy_all_documentation(source_dataset, target_dataset)
                logger.info(f"Copied {copied} files to forked dataset")
                
            except Exception as e:
                logger.error(f"Forking dataset failed, rolling back transaction. Error: {e}")
                raise
        
        # Re-fetch to get committed state
        return self.get_dataset(target_dataset)
    
    def sync_datasets(self,
                     source_dataset: str,
                     target_dataset: str,
                     source_ref: str,
                     target_ref: str,
                     direction: SyncDirection = SyncDirection.SOURCE_TO_TARGET) -> SyncOperation:
        """
        Synchronize changes between datasets.
        
        Args:
            source_dataset: Source dataset name
            target_dataset: Target dataset name
            source_ref: Git ref for source
            target_ref: Git ref for target
            direction: Sync direction
            
        Returns:
            Sync operation details
        """
        # Validate datasets exist
        source = self.get_dataset(source_dataset)
        target = self.get_dataset(target_dataset)
        
        if not source or not target:
            raise ValueError("Both datasets must exist")
        
        # Create sync operation
        sync_op = SyncOperation(
            source_dataset_id=source_dataset,
            target_dataset_id=target_dataset,
            direction=direction,
            source_ref=source_ref,
            target_ref=target_ref,
            started_at=datetime.now()
        )
        
        try:
            # Perform synchronization
            if direction == SyncDirection.SOURCE_TO_TARGET:
                files_synced = self.synchronizer.sync_changes(
                    source_dataset, target_dataset, source_ref, target_ref
                )
            elif direction == SyncDirection.BIDIRECTIONAL:
                # Bidirectional sync requires complex 3-way merge logic
                raise NotImplementedError(
                    "Bidirectional sync is not yet supported. "
                    "Please perform two separate syncs or resolve conflicts manually."
                )
                # Proper implementation would require:
                # 1. Finding common ancestor commit
                # 2. Getting diffs from ancestor to both refs
                # 3. Merging changes and detecting conflicts
                # 4. Applying merged changes or reporting conflicts
            else:
                files_synced = self.synchronizer.sync_changes(
                    target_dataset, source_dataset, target_ref, source_ref
                )
            
            sync_op.files_synced = files_synced
            sync_op.completed_at = datetime.now()
            
        except Exception as e:
            sync_op.errors.append(str(e))
            logger.error(f"Sync failed: {e}")
            raise
        
        return sync_op
    
    def delete_dataset(self, dataset_name: str, force: bool = False) -> bool:
        """
        Delete a dataset and all associated data.
        
        Args:
            dataset_name: Dataset to delete
            force: Force deletion even if dataset has children
            
        Returns:
            True if deleted successfully
            
        Raises:
            ValueError: If dataset has children and force=False
        """
        dataset = self.get_dataset(dataset_name)
        if not dataset:
            return False
        
        # Check for child datasets
        children = self.list_datasets(parent_id=dataset_name)
        if children and not force:
            raise ValueError(
                f"Dataset '{dataset_name}' has {len(children)} child datasets. "
                "Use force=True to delete anyway."
            )
        
        # Use transaction for atomic deletion
        with self.storage.transaction() as txn_storage:
            try:
                # Delete all file documentation
                logger.info(f"Deleting all documentation for dataset '{dataset_name}'")
                deleted_files = txn_storage.delete_all_documentation(dataset_name)
                logger.info(f"Deleted {deleted_files} file documentation entries")
                
                # Delete dataset metadata
                success = txn_storage.delete_dataset(dataset_name)
                
                if not success:
                    raise RuntimeError(f"Failed to delete dataset metadata for '{dataset_name}'")
                
                logger.info(f"Successfully deleted dataset '{dataset_name}'")
                return True
                
            except Exception as e:
                logger.error(f"Failed to delete dataset '{dataset_name}': {e}")
                raise
    
    def get_dataset_stats(self, dataset_name: str) -> DatasetStats:
        """
        Get statistics about a dataset.
        
        Args:
            dataset_name: Dataset to analyze
            
        Returns:
            Dataset statistics
        """
        dataset = self.get_dataset(dataset_name)
        if not dataset:
            raise ValueError(f"Dataset '{dataset_name}' not found")
        
        # Delegate to storage backend for efficient calculation
        # This avoids N+1 query problem and uses optimized SQL
        return self.storage.get_dataset_statistics(dataset_name)
    
    def get_dataset_diff(self, dataset1: str, dataset2: str) -> DatasetDiff:
        """
        Compare two datasets and return differences.
        
        Args:
            dataset1: First dataset
            dataset2: Second dataset
            
        Returns:
            Differences between datasets
        """
        # Get file lists
        files1 = set(self.storage.get_dataset_files(dataset1))
        files2 = set(self.storage.get_dataset_files(dataset2))
        
        # Calculate differences
        added = list(files2 - files1)
        deleted = list(files1 - files2)
        
        # Check for modifications in common files
        common = files1 & files2
        modified = []
        
        for filepath in common:
            # Get lightweight docs without content for comparison
            doc1 = self.storage.get_file_documentation(filepath, dataset1, include_content=False)
            doc2 = self.storage.get_file_documentation(filepath, dataset2, include_content=False)
            
            if doc1 and doc2:
                # Compare by content hash for reliability
                if doc1.content_hash != doc2.content_hash:
                    modified.append(filepath)
        
        return DatasetDiff(
            added_files=sorted(added),
            modified_files=sorted(modified),
            deleted_files=sorted(deleted)
        )
    
    def cleanup_orphaned_datasets(self, dry_run: bool = True) -> List[str]:
        """
        Find and optionally remove orphaned worktree datasets.
        
        Args:
            dry_run: If True, only list orphans without deleting
            
        Returns:
            List of orphaned dataset names
        """
        orphans = []
        worktree_datasets = self.list_datasets(dataset_type=DatasetType.WORKTREE)
        
        for dataset in worktree_datasets:
            # Check if worktree still exists
            if not self.worktree_handler.worktree_exists(dataset.source_dir):
                orphans.append(dataset.dataset_id)
                
                if not dry_run:
                    logger.info(f"Deleting orphaned dataset: {dataset.dataset_id}")
                    self.delete_dataset(dataset.dataset_id, force=True)
        
        return orphans
    
    def _metadata_to_dataset(self, metadata: DatasetMetadata) -> Dataset:
        """Convert storage metadata to domain model."""
        return Dataset(
            dataset_id=metadata.dataset_id,
            source_dir=metadata.source_dir,
            dataset_type=DatasetType(metadata.dataset_type),
            created_at=metadata.loaded_at,
            updated_at=metadata.updated_at,  # Use dedicated updated_at field
            files_count=metadata.files_count,
            parent_dataset_id=metadata.parent_dataset_id,
            source_branch=metadata.source_branch
        )
    
    def _create_dataset_transactional(self, 
                                     storage: StorageBackend,
                                     dataset_name: str,
                                     source_dir: str,
                                     dataset_type: DatasetType,
                                     parent_id: Optional[str] = None) -> Dataset:
        """Create dataset within a transaction context."""
        # Validate within transaction
        existing = storage.get_dataset_metadata(dataset_name)
        if existing:
            raise DatasetValidationError("dataset_name", dataset_name, "Dataset already exists")
        
        # Detect worktree if needed
        branch = None
        if dataset_type == DatasetType.MAIN and self.worktree_handler.is_worktree(source_dir):
            dataset_type = DatasetType.WORKTREE
            branch = self.worktree_handler.get_worktree_branch(source_dir)
        
        # Create in storage
        success = storage.create_dataset(
            dataset_id=dataset_name,
            source_dir=source_dir,
            dataset_type=dataset_type.value,
            parent_id=parent_id,
            source_branch=branch
        )
        
        if not success:
            raise RuntimeError(f"Failed to create dataset {dataset_name}")
        
        # Return dataset object (within transaction)
        metadata = storage.get_dataset_metadata(dataset_name)
        return self._metadata_to_dataset(metadata)
```

### dataset/dataset_sync.py
```python
import logging
from typing import List, Set, Tuple
from datetime import datetime

from storage.backend import StorageBackend
from storage.models import FileDocumentation
from helpers.git_helper import GitHelper

logger = logging.getLogger(__name__)

class DatasetSynchronizer:
    """Handles synchronization between datasets."""
    
    def __init__(self, storage_backend: StorageBackend):
        self.storage = storage_backend
        self.git = GitHelper()
    
    def sync_changes(self,
                    source_dataset: str,
                    target_dataset: str,
                    source_ref: str,
                    target_ref: str) -> int:
        """
        Sync changes from source to target dataset.
        
        Args:
            source_dataset: Source dataset name
            target_dataset: Target dataset name
            source_ref: Git ref for source changes
            target_ref: Git ref for target base
            
        Returns:
            Number of files synchronized
        """
        # Get changed files between refs
        changed_files = self._get_changed_files(source_ref, target_ref)
        logger.info(f"Found {len(changed_files)} changed files between {source_ref} and {target_ref}")
        
        synced_count = 0
        
        for filepath, change_type in changed_files:
            if change_type == 'D':
                # File was deleted
                success = self.storage.delete_documentation(filepath, target_dataset)
                if success:
                    synced_count += 1
                    logger.debug(f"Deleted {filepath} from {target_dataset}")
            else:
                # File was added or modified
                doc = self.storage.get_file_documentation(filepath, source_dataset)
                if doc:
                    # Create a copy to avoid side effects
                    from copy import deepcopy
                    target_doc = deepcopy(doc)
                    target_doc.dataset = target_dataset
                    target_doc.documented_at = datetime.now()
                    success = self.storage.insert_documentation(target_doc)
                    if success:
                        synced_count += 1
                        logger.debug(f"Synced {filepath} to {target_dataset}")
                else:
                    logger.warning(f"Could not find documentation for {filepath} in {source_dataset}")
        
        logger.info(f"Successfully synced {synced_count} files from {source_dataset} to {target_dataset}")
        return synced_count
    
    def copy_all_documentation(self, source_dataset: str, target_dataset: str) -> int:
        """
        Copy all file documentation from source to target.
        
        Args:
            source_dataset: Source dataset name
            target_dataset: Target dataset name
            
        Returns:
            Number of files copied
        """
        # Get all files in source
        source_files = self.storage.get_dataset_files(source_dataset)
        logger.info(f"Copying {len(source_files)} files from {source_dataset} to {target_dataset}")
        
        # Batch copy for efficiency
        batch_size = 100
        total_copied = 0
        
        for i in range(0, len(source_files), batch_size):
            batch = source_files[i:i + batch_size]
            docs = []
            
            for filepath in batch:
                doc = self.storage.get_file_documentation(filepath, source_dataset, include_content=True)
                if doc:
                    # Update dataset reference
                    doc.dataset = target_dataset
                    docs.append(doc)
            
            if docs:
                result = self.storage.insert_documentation_batch(docs)
                total_copied += result.successful
                
                if result.failed > 0:
                    logger.warning(f"Failed to copy {result.failed} files in batch")
        
        logger.info(f"Successfully copied {total_copied} files")
        return total_copied
    
    def _get_changed_files(self, source_ref: str, target_ref: str) -> List[Tuple[str, str]]:
        """
        Get list of changed files between two git refs.
        
        Returns:
            List of (filepath, change_type) tuples
        """
        try:
            # Use git diff to find changes
            output = self.git.run_command(
                ["git", "diff", "--name-status", f"{target_ref}...{source_ref}"]
            )
            
            changes = []
            for line in output.strip().split('\n'):
                if not line:
                    continue
                    
                parts = line.split('\t')
                if len(parts) >= 2:
                    change_type = parts[0]
                    filepath = parts[1]
                    changes.append((filepath, change_type))
            
            return changes
            
        except Exception as e:
            logger.error(f"Failed to get changed files: {e}")
            return []
```

### dataset/worktree_handler.py
```python
import os
import logging
from typing import Optional, List, Dict
from pathlib import Path

from helpers.git_helper import GitHelper

logger = logging.getLogger(__name__)

class WorktreeHandler:
    """Handles Git worktree detection and management."""
    
    def __init__(self, git_helper: Optional[GitHelper] = None):
        self.git = git_helper or GitHelper()
    
    def is_worktree(self, directory: str) -> bool:
        """
        Check if directory is a Git worktree.
        
        Args:
            directory: Directory to check
            
        Returns:
            True if directory is a worktree
        """
        try:
            # Check if it's a git repository first
            if not self.git.is_git_repository(directory):
                return False
            
            # Get git directory
            git_dir = self.git.run_command(
                ["git", "rev-parse", "--git-dir"],
                cwd=directory
            ).strip()
            
            # Worktrees have .git files, not directories
            git_path = Path(directory) / ".git"
            if git_path.is_file():
                return True
            
            # Also check if git-dir is outside the working directory
            if not git_dir.startswith(directory):
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking worktree status: {e}")
            return False
    
    def get_worktree_branch(self, directory: str) -> Optional[str]:
        """
        Get the branch name for a worktree.
        
        Args:
            directory: Worktree directory
            
        Returns:
            Branch name or None
        """
        try:
            branch = self.git.run_command(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=directory
            ).strip()
            
            return branch if branch != "HEAD" else None
            
        except Exception as e:
            logger.error(f"Failed to get worktree branch: {e}")
            return None
    
    def get_main_repository(self, worktree_dir: str) -> Optional[str]:
        """
        Get the main repository path for a worktree.
        
        Args:
            worktree_dir: Worktree directory
            
        Returns:
            Path to main repository
        """
        try:
            # Get the common git directory
            common_dir = self.git.run_command(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=worktree_dir
            ).strip()
            
            # Main repo is parent of common dir
            return str(Path(common_dir).parent)
            
        except Exception as e:
            logger.error(f"Failed to get main repository: {e}")
            return None
    
    def list_worktrees(self, main_repo: str) -> List[Dict[str, str]]:
        """
        List all worktrees for a repository.
        
        Args:
            main_repo: Main repository path
            
        Returns:
            List of worktree info dicts
        """
        try:
            output = self.git.run_command(
                ["git", "worktree", "list", "--porcelain"],
                cwd=main_repo
            )
            
            worktrees = []
            current = {}
            
            for line in output.strip().split('\n'):
                if not line:
                    if current:
                        worktrees.append(current)
                        current = {}
                elif line.startswith("worktree "):
                    current['path'] = line[9:]
                elif line.startswith("branch "):
                    current['branch'] = line[7:]
                elif line.startswith("HEAD "):
                    current['head'] = line[5:]
            
            if current:
                worktrees.append(current)
            
            return worktrees
            
        except Exception as e:
            logger.error(f"Failed to list worktrees: {e}")
            return []
    
    def worktree_exists(self, worktree_path: str) -> bool:
        """
        Check if a worktree path still exists and is valid.
        
        Args:
            worktree_path: Path to check
            
        Returns:
            True if worktree exists and is valid
        """
        # Check if directory exists
        if not os.path.exists(worktree_path):
            return False
        
        # Check if it's still a valid worktree
        return self.is_worktree(worktree_path)
    
    def get_worktree_dataset_name(self, 
                                 main_dataset: str,
                                 branch: str) -> str:
        """
        Generate dataset name for a worktree.
        
        Args:
            main_dataset: Main dataset name
            branch: Worktree branch name
            
        Returns:
            Generated dataset name
        """
        # Clean branch name for use in dataset name
        clean_branch = branch.replace('/', '_').replace('-', '_')
        return f"{main_dataset}__wt_{clean_branch}"
```

### dataset/dataset_validator.py
```python
import os
import re
from typing import Optional
from pathlib import Path

from .dataset_models import DatasetValidationError

class DatasetValidator:
    """Validates dataset operations."""
    
    # Valid dataset name pattern
    DATASET_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')
    MAX_DATASET_NAME_LENGTH = 100
    
    def validate_dataset_name(self, name: str) -> None:
        """
        Validate dataset name format.
        
        Args:
            name: Dataset name to validate
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if not name:
            raise DatasetValidationError("name", name, "Dataset name cannot be empty")
        
        if len(name) > self.MAX_DATASET_NAME_LENGTH:
            raise DatasetValidationError(
                "name", name, 
                f"Dataset name cannot exceed {self.MAX_DATASET_NAME_LENGTH} characters"
            )
        
        if not self.DATASET_NAME_PATTERN.match(name):
            raise DatasetValidationError(
                "name", name,
                "Dataset name must start with alphanumeric and contain only "
                "alphanumeric, underscore, or hyphen characters"
            )
        
        # Reserved names
        reserved = {'test', 'temp', 'tmp', 'cache', 'system'}
        if name.lower() in reserved:
            raise DatasetValidationError(
                "name", name,
                f"'{name}' is a reserved dataset name"
            )
    
    def validate_source_directory(self, directory: str) -> None:
        """
        Validate source directory exists and is readable.
        
        Args:
            directory: Directory path to validate
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if not directory:
            raise DatasetValidationError(
                "directory", directory,
                "Source directory cannot be empty"
            )
        
        path = Path(directory)
        
        if not path.exists():
            raise DatasetValidationError(
                "directory", directory,
                "Source directory does not exist"
            )
        
        if not path.is_dir():
            raise DatasetValidationError(
                "directory", directory,
                "Source path is not a directory"
            )
        
        if not os.access(directory, os.R_OK):
            raise DatasetValidationError(
                "directory", directory,
                "Source directory is not readable"
            )
    
    def validate_parent_dataset(self, 
                               parent_id: Optional[str],
                               dataset_type: str) -> None:
        """
        Validate parent dataset requirements.
        
        Args:
            parent_id: Parent dataset ID
            dataset_type: Type of dataset being created
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if dataset_type in ('fork', 'worktree') and not parent_id:
            raise DatasetValidationError(
                "parent_id", parent_id,
                f"Dataset type '{dataset_type}' requires a parent dataset"
            )
        
        if parent_id:
            self.validate_dataset_name(parent_id)
```

## Testing Plan

### Unit Tests

#### test_dataset_service.py
```python
def test_create_dataset():
    """Test basic dataset creation."""
    mock_storage = Mock(StorageBackend)
    service = DatasetService(mock_storage)
    
    dataset = service.create_dataset("test-dataset", "/path/to/source")
    assert dataset.dataset_id == "test-dataset"
    assert dataset.dataset_type == DatasetType.MAIN

def test_fork_dataset():
    """Test dataset forking with documentation copy."""
    # Test that forking copies all documentation
    # Test transaction rollback on failure
    
def test_fork_dataset_atomicity():
    """Test fork operation is atomic."""
    # Mock storage to fail during copy
    # Verify entire operation is rolled back
    
def test_sync_datasets():
    """Test dataset synchronization."""
    # Test sync operation with mocked git changes
    # Test bidirectional sync raises NotImplementedError
    
def test_delete_dataset_with_children():
    """Test deletion validation with child datasets."""
    # Should fail without force=True
    
def test_delete_dataset_atomicity():
    """Test delete operation is atomic."""
    # Mock storage to fail during metadata deletion
    # Verify files are not deleted if metadata deletion fails
    
def test_cleanup_orphaned_datasets():
    """Test orphaned worktree cleanup."""
    # Mock worktree that no longer exists
```

#### test_dataset_sync.py
```python
def test_sync_changes_with_deletes():
    """Test sync handles file deletions."""
    
def test_copy_all_documentation_batch():
    """Test batch copying efficiency."""
    
def test_get_changed_files():
    """Test git diff parsing."""

def test_content_hash_diff():
    """Test using content hashes for modification detection."""
    # Ensure get_dataset_diff uses content_hash not timestamps
```

#### test_worktree_handler.py
```python
def test_is_worktree_detection():
    """Test worktree detection logic."""
    
def test_get_worktree_branch():
    """Test branch name extraction."""
    
def test_list_worktrees():
    """Test worktree listing."""
```

#### test_dataset_validator.py
```python
def test_validate_dataset_name():
    """Test name validation rules."""
    validator = DatasetValidator()
    
    # Valid names
    validator.validate_dataset_name("my-dataset")
    validator.validate_dataset_name("dataset_123")
    
    # Invalid names
    with pytest.raises(DatasetValidationError):
        validator.validate_dataset_name("")
    
    with pytest.raises(DatasetValidationError):
        validator.validate_dataset_name("test")  # reserved
    
    with pytest.raises(DatasetValidationError):
        validator.validate_dataset_name("my dataset")  # spaces
```

### Integration Tests
```python
def test_full_dataset_lifecycle():
    """Test complete dataset lifecycle."""
    # Create main dataset
    # Fork for feature branch
    # Make changes
    # Sync back to main
    # Delete fork
    
def test_worktree_workflow():
    """Test worktree-specific workflow."""
    # Detect worktree
    # Create worktree dataset
    # Handle branch switching
    # Cleanup on worktree removal
```

## Migration Strategy

### Phase 1: Extract Core Functionality
1. Create dataset module structure
2. Move dataset operations from sqlite_storage.py
3. Keep sqlite_storage.py methods as thin wrappers initially

### Phase 2: Add New Features
1. Implement comprehensive validation
2. Add dataset statistics
3. Enhance sync capabilities
4. Improve worktree support

### Phase 3: Update Consumers
1. Update MCP tools to use DatasetService
2. Migrate git hooks to use new APIs
3. Update documentation workflows

## Integration with Storage Backend

### Required Storage Backend Methods
```python
# New methods needed in StorageBackend
@abstractmethod
def delete_all_documentation(self, dataset_id: str) -> int:
    """Delete all documentation for a dataset."""
    
@abstractmethod
def get_dataset_files(self, dataset_id: str) -> List[str]:
    """Get all file paths in a dataset."""
    
@abstractmethod
def get_dataset_statistics(self, dataset_id: str) -> DatasetStats:
    """Calculate and return statistics for a dataset efficiently."""
    
@abstractmethod
def transaction(self):
    """Context manager for transactional operations."""
```

### Update sqlite_storage.py
```python
# Add delegation to DatasetService
class SqliteStorage:
    def __init__(self, db_path: str):
        # ... existing init ...
        self.dataset_service = DatasetService(self.backend)
    
    def create_dataset(self, dataset_name: str, source_dir: str):
        """Delegate to DatasetService."""
        dataset = self.dataset_service.create_dataset(
            dataset_name, source_dir
        )
        return dataset is not None
```

## Performance Considerations

1. **Batch Operations**:
   - Copy documentation in batches of 100
   - Use transactions for multi-step operations
   - Optimize sync to only transfer changes

2. **Caching**:
   - Cache dataset metadata
   - Cache worktree status checks
   - Invalidate on changes

3. **Lazy Loading**:
   - Don't load file content unless needed
   - Stream large datasets
   - Paginate file lists

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dataset deletion data loss | High | Require force flag, log all deletions, use transactions |
| Sync conflicts | Medium | Remove bidirectional sync until 3-way merge implemented |
| Orphaned datasets | Low | Regular cleanup job, validation |
| Performance with large datasets | Medium | Delegate statistics to storage backend, batch operations |
| Worktree detection failures | Low | Fallback to manual dataset type |
| Non-atomic operations | High | Wrap multi-step operations in transactions |
| Stale diff detection | Medium | Use content hashes instead of timestamps |

## Success Criteria

1. **Functionality**:
   - All dataset operations through service
   - Clean lifecycle management
   - Robust sync capabilities

2. **Performance**:
   - Batch operations 10x faster
   - Sub-second dataset queries
   - Efficient sync transfers

3. **Reliability**:
   - No data loss on deletion
   - Atomic sync operations
   - Proper transaction boundaries

4. **Maintainability**:
   - Clear domain boundaries
   - Comprehensive validation
   - Well-tested edge cases

## Documentation Updates

1. Document DatasetService API
2. Add dataset lifecycle guide
3. Document sync strategies
4. Worktree workflow examples

## Review Checklist

- [ ] DatasetService API complete
- [ ] Lifecycle operations tested
- [ ] Sync logic robust
- [ ] Worktree support working
- [ ] Validation comprehensive
- [ ] Batch operations efficient
- [ ] Integration smooth
- [ ] Documentation complete