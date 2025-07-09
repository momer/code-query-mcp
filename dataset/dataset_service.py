"""Main dataset service for lifecycle management."""

from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from .dataset_models import (
    Dataset, DatasetType, SyncOperation, DatasetStats, 
    DatasetDiff, DatasetValidationError, SyncDirection
)
from .dataset_sync import DatasetSynchronizer
from .worktree_handler import WorktreeHandler
from .dataset_validator import DatasetValidator
from storage.backend import StorageBackend
from storage.models import DatasetMetadata, FileDocumentation
from helpers.git_operations import GitHelper

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
        self.validator.validate_parent_dataset(parent_id, dataset_type.value)
        
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
        # Get all metadata in a single query
        all_metadata = self.storage.list_datasets()
        
        # Apply filters before converting to domain objects to reduce memory usage
        filtered_metadata = all_metadata
        
        if dataset_type:
            filtered_metadata = [m for m in filtered_metadata if m.dataset_type == dataset_type.value]
        
        if parent_id:
            filtered_metadata = [m for m in filtered_metadata if m.parent_dataset_id == parent_id]
        
        # Convert only filtered results to domain objects
        return [self._metadata_to_dataset(m) for m in filtered_metadata]
    
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
        
        # Use transaction for atomic deletion
        with self.storage.transaction() as txn_storage:
            try:
                # Check for child datasets inside transaction for consistency
                all_metadata = txn_storage.list_datasets()
                children = [m for m in all_metadata if m.parent_dataset_id == dataset_name]
                
                if children and not force:
                    raise ValueError(
                        f"Dataset '{dataset_name}' has {len(children)} child datasets. "
                        "Use force=True to delete anyway."
                    )
                
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
        common = list(files1 & files2)
        modified = []
        
        if common:
            # Batch retrieve documentation for all common files
            docs1 = self.storage.get_file_documentation_batch(dataset1, common, include_content=False)
            docs2 = self.storage.get_file_documentation_batch(dataset2, common, include_content=False)
            
            # Compare content hashes
            for filepath in common:
                doc1 = docs1.get(filepath)
                doc2 = docs2.get(filepath)
                
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