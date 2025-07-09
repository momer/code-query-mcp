"""Handles synchronization between datasets."""

import logging
from typing import List, Set, Tuple
from datetime import datetime
from copy import deepcopy
import subprocess

from storage.backend import StorageBackend
from storage.models import FileDocumentation

logger = logging.getLogger(__name__)


class DatasetSynchronizer:
    """Handles synchronization between datasets."""
    
    def __init__(self, storage_backend: StorageBackend):
        self.storage = storage_backend
    
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
        
        # Separate deletions from additions/modifications
        files_to_delete = []
        files_to_sync = []
        
        for filepath, change_type in changed_files:
            if change_type == 'D':
                files_to_delete.append(filepath)
            else:
                files_to_sync.append(filepath)
        
        synced_count = 0
        
        # Handle deletions
        for filepath in files_to_delete:
            success = self.storage.delete_documentation(filepath, target_dataset)
            if success:
                synced_count += 1
                logger.debug(f"Deleted {filepath} from {target_dataset}")
        
        # Batch process additions/modifications
        if files_to_sync:
            # Get all documentation in batch
            source_docs = self.storage.get_file_documentation_batch(source_dataset, files_to_sync, include_content=True)
            
            # Prepare documents for target dataset
            target_docs = []
            for filepath in files_to_sync:
                doc = source_docs.get(filepath)
                if doc:
                    # Create a deep copy to avoid side effects
                    target_doc = deepcopy(doc)
                    target_doc.dataset = target_dataset
                    target_doc.documented_at = datetime.now()
                    target_docs.append(target_doc)
                else:
                    logger.warning(f"Could not find documentation for {filepath} in {source_dataset}")
            
            # Batch insert
            if target_docs:
                result = self.storage.insert_documentation_batch(target_docs)
                synced_count += result.successful
                
                if result.failed > 0:
                    logger.warning(f"Failed to sync {result.failed} files")
        
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
            
            # Get all documentation for this batch in a single query
            batch_docs = self.storage.get_file_documentation_batch(source_dataset, batch, include_content=True)
            
            # Prepare documents for target dataset
            docs = []
            for filepath in batch:
                doc = batch_docs.get(filepath)
                if doc:
                    # Create a deep copy and update dataset reference
                    doc_copy = deepcopy(doc)
                    doc_copy.dataset = target_dataset
                    docs.append(doc_copy)
            
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
            output = subprocess.check_output(
                ["git", "diff", "--name-status", f"{target_ref}...{source_ref}"],
                text=True,
                stderr=subprocess.DEVNULL
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