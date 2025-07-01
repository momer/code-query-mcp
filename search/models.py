"""Models for the search service."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class FileMetadata:
    """Metadata for a file in the search index."""
    file_id: int
    file_path: str
    file_name: str
    file_extension: str
    file_size: int
    last_modified: str
    content_hash: str
    dataset_id: str
    overview: Optional[str] = None
    language: Optional[str] = None
    functions: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)


@dataclass 
class SearchResult:
    """Result from a search operation with full context."""
    file_path: str
    dataset_id: str
    match_content: str
    match_type: str  # 'metadata' or 'content'
    relevance_score: float
    snippet: Optional[str] = None
    metadata: Optional[FileMetadata] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            'file_path': self.file_path,
            'dataset_id': self.dataset_id,
            'match_content': self.match_content,
            'match_type': self.match_type,
            'relevance_score': self.relevance_score,
            'snippet': self.snippet
        }
        if self.metadata:
            result['metadata'] = {
                'file_name': self.metadata.file_name,
                'file_extension': self.metadata.file_extension,
                'overview': self.metadata.overview,
                'language': self.metadata.language,
                'functions': self.metadata.functions,
                'exports': self.metadata.exports
            }
        return result