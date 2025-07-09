"""Data Transfer Objects (DTOs) for Code Query MCP Server storage layer."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class SearchResult:
    """Result from a search operation."""
    filepath: str
    filename: str
    dataset: str
    score: float
    snippet: str
    overview: Optional[str] = None
    ddd_context: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'filepath': self.filepath,
            'filename': self.filename,
            'dataset': self.dataset,
            'score': self.score,
            'snippet': self.snippet,
            'overview': self.overview,
            'ddd_context': self.ddd_context
        }


@dataclass
class FileDocumentation:
    """Complete documentation for a file."""
    filepath: str
    filename: str
    overview: str
    dataset: str
    ddd_context: Optional[str] = None
    functions: Optional[Dict[str, Any]] = None
    exports: Optional[Dict[str, Any]] = None
    imports: Optional[Dict[str, Any]] = None
    types_interfaces_classes: Optional[Dict[str, Any]] = None
    constants: Optional[Dict[str, Any]] = None
    dependencies: Optional[List[str]] = None
    other_notes: Optional[List[str]] = None
    full_content: Optional[str] = None
    documented_at_commit: Optional[str] = None
    documented_at: Optional[datetime] = None
    content_hash: Optional[str] = None


@dataclass
class DatasetMetadata:
    """Metadata for a dataset."""
    dataset_id: str
    source_dir: str
    files_count: int
    loaded_at: datetime
    dataset_type: str = 'main'
    parent_dataset_id: Optional[str] = None
    source_branch: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'dataset_id': self.dataset_id,
            'source_dir': self.source_dir,
            'files_count': self.files_count,
            'loaded_at': self.loaded_at.isoformat() if self.loaded_at else None,
            'dataset_type': self.dataset_type,
            'parent_dataset_id': self.parent_dataset_id,
            'source_branch': self.source_branch,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


@dataclass
class BatchOperationResult:
    """Result of a batch operation."""
    total_items: int
    successful: int
    failed: int
    error_details: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_error(self, item_id: str, error_msg: str):
        """Add an error detail for a specific item."""
        self.error_details.append({
            'item_id': item_id,
            'error': error_msg
        })
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.successful / self.total_items) * 100