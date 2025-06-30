"""Search service with dependency injection and feature flags for flexible search behavior."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum

from ..storage.models import FileMetadata, SearchResult
from .query_builder import FTS5QueryBuilder


class SearchMode(Enum):
    """Available search modes."""
    UNIFIED = "unified"
    METADATA_ONLY = "metadata_only"
    CONTENT_ONLY = "content_only"


@dataclass
class SearchConfig:
    """Configuration for search behavior."""
    enable_fallback: bool = True
    enable_code_aware: bool = True
    enable_snippet_generation: bool = True
    enable_relevance_scoring: bool = True
    max_results: int = 50
    snippet_context_chars: int = 64
    min_relevance_score: float = 0.0
    search_mode: SearchMode = SearchMode.UNIFIED
    deduplicate_results: bool = True


class SearchServiceInterface(ABC):
    """Interface for search services."""
    
    @abstractmethod
    def search(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[SearchResult]:
        """
        Execute a search query.
        
        Args:
            query: The search query
            dataset_id: The dataset to search in
            config: Optional search configuration
            
        Returns:
            List of search results
        """
        pass
    
    @abstractmethod
    def search_metadata(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[FileMetadata]:
        """
        Search only in file metadata.
        
        Args:
            query: The search query
            dataset_id: The dataset to search in
            config: Optional search configuration
            
        Returns:
            List of file metadata results
        """
        pass
    
    @abstractmethod
    def search_content(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[SearchResult]:
        """
        Search only in file content.
        
        Args:
            query: The search query
            dataset_id: The dataset to search in
            config: Optional search configuration
            
        Returns:
            List of search results with content matches
        """
        pass


class SearchService(SearchServiceInterface):
    """Implementation of search service with query building and feature flags."""
    
    def __init__(
        self,
        storage_backend,
        query_builder: Optional[FTS5QueryBuilder] = None,
        default_config: Optional[SearchConfig] = None
    ):
        """
        Initialize search service.
        
        Args:
            storage_backend: The storage backend for executing queries
            query_builder: Optional query builder instance
            default_config: Optional default configuration
        """
        self.storage = storage_backend
        self.query_builder = query_builder or FTS5QueryBuilder()
        self.default_config = default_config or SearchConfig()
    
    def search(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[SearchResult]:
        """Execute a unified search based on configuration."""
        config = config or self.default_config
        
        # Route to appropriate search method based on mode
        if config.search_mode == SearchMode.METADATA_ONLY:
            # Convert metadata results to search results
            metadata_results = self.search_metadata(query, dataset_id, config)
            return [self._metadata_to_search_result(m) for m in metadata_results]
        
        elif config.search_mode == SearchMode.CONTENT_ONLY:
            return self.search_content(query, dataset_id, config)
        
        else:  # UNIFIED mode
            return self._unified_search(query, dataset_id, config)
    
    def search_metadata(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[FileMetadata]:
        """Search only in file metadata."""
        config = config or self.default_config
        
        # Build query variants if fallback enabled
        if config.enable_fallback:
            query_variants = self.query_builder.get_query_variants(query)
        else:
            query_variants = [self.query_builder.build_query(query)]
        
        results = []
        seen_paths = set()
        
        for variant in query_variants:
            try:
                # Execute metadata search
                variant_results = self.storage.search_files(
                    query=variant,
                    dataset_id=dataset_id,
                    limit=config.max_results
                )
                
                # Deduplicate if enabled
                if config.deduplicate_results:
                    for result in variant_results:
                        if result.file_path not in seen_paths:
                            seen_paths.add(result.file_path)
                            results.append(result)
                else:
                    results.extend(variant_results)
                
                # Stop if we have enough results
                if len(results) >= config.max_results:
                    break
                    
            except Exception:
                # Continue with next variant on error
                continue
        
        return results[:config.max_results]
    
    def search_content(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[SearchResult]:
        """Search only in file content."""
        config = config or self.default_config
        
        # Build query variants if fallback enabled
        if config.enable_fallback:
            query_variants = self.query_builder.get_query_variants(query)
        else:
            query_variants = [self.query_builder.build_query(query)]
        
        results = []
        seen_content = set()
        
        for variant in query_variants:
            try:
                # Execute content search
                variant_results = self.storage.search_full_content(
                    query=variant,
                    dataset_id=dataset_id,
                    limit=config.max_results,
                    include_snippets=config.enable_snippet_generation
                )
                
                # Apply relevance filter if enabled
                if config.enable_relevance_scoring and config.min_relevance_score > 0:
                    variant_results = [
                        r for r in variant_results 
                        if r.relevance_score >= config.min_relevance_score
                    ]
                
                # Deduplicate if enabled
                if config.deduplicate_results:
                    for result in variant_results:
                        content_key = (result.file_path, result.match_content)
                        if content_key not in seen_content:
                            seen_content.add(content_key)
                            results.append(result)
                else:
                    results.extend(variant_results)
                
                # Stop if we have enough results
                if len(results) >= config.max_results:
                    break
                    
            except Exception:
                # Continue with next variant on error
                continue
        
        return results[:config.max_results]
    
    def _unified_search(
        self,
        query: str,
        dataset_id: str,
        config: SearchConfig
    ) -> List[SearchResult]:
        """Execute unified search combining metadata and content."""
        # Get metadata results
        metadata_results = self.search_metadata(query, dataset_id, config)
        metadata_paths = {m.file_path for m in metadata_results}
        
        # Get content results
        content_results = self.search_content(query, dataset_id, config)
        
        # Combine results with deduplication
        combined_results = []
        seen_paths = set()
        
        # Add content results first (they have snippets)
        for result in content_results:
            if config.deduplicate_results:
                if result.file_path not in seen_paths:
                    seen_paths.add(result.file_path)
                    combined_results.append(result)
            else:
                combined_results.append(result)
        
        # Add metadata-only results
        for metadata in metadata_results:
            if metadata.file_path not in seen_paths:
                search_result = self._metadata_to_search_result(metadata)
                combined_results.append(search_result)
                seen_paths.add(metadata.file_path)
        
        # Sort by relevance if enabled
        if config.enable_relevance_scoring:
            combined_results.sort(key=lambda r: r.relevance_score, reverse=True)
        
        return combined_results[:config.max_results]
    
    def _metadata_to_search_result(self, metadata: FileMetadata) -> SearchResult:
        """Convert FileMetadata to SearchResult."""
        return SearchResult(
            file_path=metadata.file_path,
            dataset_id=metadata.dataset_id,
            match_content=metadata.overview or "",
            match_type="metadata",
            relevance_score=0.5,  # Default score for metadata-only matches
            snippet=None,
            metadata=metadata
        )