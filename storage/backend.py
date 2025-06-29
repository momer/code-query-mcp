"""Abstract storage backend interface for Code Query MCP Server."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from .models import SearchResult, FileDocumentation, DatasetMetadata, BatchOperationResult


class StorageBackend(ABC):
    """Domain-oriented storage interface.
    
    This abstract base class defines the storage contract that all implementations
    must fulfill. It provides a clean, SQL-agnostic interface for data operations.
    """
    
    # Search Operations
    @abstractmethod
    def search_metadata(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against indexed metadata fields.
        
        Searches through file overview, function names, exports, imports, etc.
        Does not search file content.
        
        Args:
            fts_query: FTS5-compatible query string
            dataset: Dataset ID to search within
            limit: Maximum number of results to return
            
        Returns:
            List of SearchResult objects ordered by relevance
        """
        pass
        
    @abstractmethod
    def search_content(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against full file content.
        
        Searches only the full_content field of indexed files.
        
        Args:
            fts_query: FTS5-compatible query string
            dataset: Dataset ID to search within
            limit: Maximum number of results to return
            
        Returns:
            List of SearchResult objects ordered by relevance
        """
        pass
        
    @abstractmethod
    def search_unified(self, fts_query: str, dataset: str, limit: int = 10) -> Tuple[List[SearchResult], List[SearchResult], Dict[str, int]]:
        """Performs both metadata and content search with deduplication.
        
        Returns results from both search types, deduplicated and with statistics.
        
        Args:
            fts_query: FTS5-compatible query string
            dataset: Dataset ID to search within
            limit: Maximum number of results per search type
            
        Returns:
            Tuple of (metadata_results, content_only_results, search_stats)
            where search_stats contains counts and deduplication info
        """
        pass
        
    # Document Operations    
    @abstractmethod
    def get_file_documentation(self, filepath: str, dataset: str, include_content: bool = False) -> Optional[FileDocumentation]:
        """Retrieve file documentation.
        
        Args:
            filepath: The path to the file (can be partial for matching)
            dataset: The dataset the file belongs to
            include_content: If True, populates the 'full_content' field
            
        Returns:
            FileDocumentation object or None if not found
        """
        pass
        
    @abstractmethod
    def insert_documentation(self, doc: FileDocumentation) -> bool:
        """Insert or update file documentation.
        
        Uses UPSERT semantics - will update if file already exists in dataset.
        
        Args:
            doc: FileDocumentation object to insert/update
            
        Returns:
            True if successful, False otherwise
        """
        pass
        
    @abstractmethod
    def insert_documentation_batch(self, docs: List[FileDocumentation]) -> BatchOperationResult:
        """Insert or update multiple file documentations efficiently.
        
        Uses batch operations for performance. All operations happen in a
        single transaction for consistency.
        
        Args:
            docs: List of FileDocumentation objects to insert/update
            
        Returns:
            BatchOperationResult with success/failure counts and details
        """
        pass
        
    @abstractmethod
    def update_documentation(self, filepath: str, dataset: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of existing documentation.
        
        Only updates fields provided in the updates dict.
        
        Args:
            filepath: Path to the file to update
            dataset: Dataset the file belongs to
            updates: Dictionary of field names to new values
            
        Returns:
            True if successful, False if file not found or error
        """
        pass
        
    @abstractmethod
    def delete_documentation(self, filepath: str, dataset: str) -> bool:
        """Remove a file's documentation from the index.
        
        Args:
            filepath: Path to the file to remove
            dataset: Dataset the file belongs to
            
        Returns:
            True if deleted, False if not found or error
        """
        pass
        
    # Dataset Operations
    @abstractmethod
    def get_dataset_metadata(self, dataset_id: str) -> Optional[DatasetMetadata]:
        """Retrieve dataset metadata.
        
        Args:
            dataset_id: ID of the dataset
            
        Returns:
            DatasetMetadata object or None if not found
        """
        pass
        
    @abstractmethod
    def list_datasets(self) -> List[DatasetMetadata]:
        """List all datasets with metadata.
        
        Returns:
            List of DatasetMetadata objects for all datasets
        """
        pass
        
    @abstractmethod
    def create_dataset(self, dataset_id: str, source_dir: str, 
                      dataset_type: str = 'main', parent_id: Optional[str] = None,
                      source_branch: Optional[str] = None) -> bool:
        """Create a new dataset.
        
        Args:
            dataset_id: Unique identifier for the dataset
            source_dir: Directory that was indexed
            dataset_type: Type of dataset ('main', 'worktree', etc.)
            parent_id: Parent dataset ID for worktree datasets
            source_branch: Git branch name for worktree datasets
            
        Returns:
            True if created successfully, False otherwise
        """
        pass
        
    @abstractmethod
    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset and all associated data.
        
        Args:
            dataset_id: ID of the dataset to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        pass
        
    @abstractmethod
    def get_dataset_files(self, dataset_id: str, limit: Optional[int] = None) -> List[str]:
        """Get all file paths in a dataset.
        
        Args:
            dataset_id: ID of the dataset
            limit: Optional limit on number of files to return
            
        Returns:
            List of file paths in the dataset
        """
        pass
        
    @abstractmethod
    def get_dataset_file_count(self, dataset_id: str) -> int:
        """Get count of files in a dataset.
        
        Args:
            dataset_id: ID of the dataset
            
        Returns:
            Number of files in the dataset
        """
        pass
        
    # Schema Operations
    @abstractmethod
    def get_schema_version(self) -> Optional[str]:
        """Get current schema version.
        
        Returns:
            Schema version string or None if not set
        """
        pass
        
    @abstractmethod
    def ensure_schema(self) -> bool:
        """Ensure database schema is properly initialized.
        
        Creates tables and indexes if they don't exist.
        Runs any necessary migrations.
        
        Returns:
            True if schema is ready, False on error
        """
        pass
        
    # Health and Maintenance
    @abstractmethod
    def vacuum(self) -> bool:
        """Optimize database storage.
        
        Runs database-specific optimization routines.
        
        Returns:
            True if successful, False otherwise
        """
        pass
        
    @abstractmethod
    def get_storage_info(self) -> Dict[str, Any]:
        """Get storage statistics and health information.
        
        Returns:
            Dictionary with storage stats (size, file count, etc.)
        """
        pass