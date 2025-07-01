"""Search service with dependency injection and feature flags for flexible search behavior."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
import logging

from .models import FileMetadata, SearchResult
from .query_builder import FTS5QueryBuilder
from .query_sanitizer import FTS5QuerySanitizer, SanitizationConfig
from .progressive_search import ProgressiveSearchStrategy, create_default_progressive_strategy
from .query_analyzer import QueryComplexityAnalyzer, ComplexityLevel

logger = logging.getLogger(__name__)


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
    enable_query_sanitization: bool = True
    enable_progressive_search: bool = True
    enable_complexity_analysis: bool = True
    max_results: int = 50
    snippet_context_chars: int = 64
    min_relevance_score: float = 0.0
    search_mode: SearchMode = SearchMode.UNIFIED
    deduplicate_results: bool = True
    query_timeout_ms: int = 5000
    # Sanitization config
    sanitization_config: Optional[SanitizationConfig] = None
    # Complexity thresholds
    max_query_terms: int = 50
    max_query_cost: float = 100.0


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
        query_sanitizer: Optional[FTS5QuerySanitizer] = None,
        query_analyzer: Optional[QueryComplexityAnalyzer] = None,
        default_config: Optional[SearchConfig] = None,
        progressive_strategy: Optional[ProgressiveSearchStrategy] = None
    ):
        """
        Initialize search service.
        
        Args:
            storage_backend: The storage backend for executing queries
            query_builder: Optional query builder instance
            query_sanitizer: Optional query sanitizer instance
            query_analyzer: Optional query complexity analyzer instance
            default_config: Optional default configuration
            progressive_strategy: Optional progressive search strategy
        """
        self.storage = storage_backend
        self.query_builder = query_builder or FTS5QueryBuilder()
        self.query_sanitizer = query_sanitizer or FTS5QuerySanitizer()
        self.query_analyzer = query_analyzer or QueryComplexityAnalyzer()
        self.default_config = default_config or SearchConfig()
        self.progressive_strategy = progressive_strategy or create_default_progressive_strategy()
    
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
        
        # Analyze query complexity if enabled
        if config.enable_complexity_analysis:
            # Configure analyzer with current config settings
            self.query_analyzer.max_terms = config.max_query_terms
            self.query_analyzer.max_cost = config.max_query_cost
            metrics = self.query_analyzer.analyze(query)
            
            if metrics.complexity_level == ComplexityLevel.TOO_COMPLEX:
                logger.warning(
                    f"Query too complex: {', '.join(metrics.warnings)}"
                )
                # Optionally return empty results or raise exception
                return []
            elif metrics.warnings:
                logger.info(f"Query complexity warnings: {', '.join(metrics.warnings)}")
        
        # Sanitize query if enabled
        if config.enable_query_sanitization:
            try:
                # Use injected sanitizer, update config if needed
                if config.sanitization_config:
                    self.query_sanitizer.config = config.sanitization_config
                query = self.query_sanitizer.sanitize(query)
                logger.debug(f"Sanitized query: {query}")
            except ValueError as e:
                logger.warning(f"Query sanitization failed: {e}")
                # Return empty results for invalid queries
                return []
        
        # Use progressive search if enabled
        if config.enable_progressive_search and config.enable_fallback:
            # Define search function for progressive strategy
            def search_func(transformed_query: str) -> List[FileMetadata]:
                return self.storage.search_files(
                    query=transformed_query,
                    dataset_id=dataset_id,
                    limit=config.max_results,
                    timeout_ms=config.query_timeout_ms
                )
            
            # Define deduplication function if needed
            dedupe_func = (lambda r: r.file_path) if config.deduplicate_results else None
            
            # Execute progressive search
            results = self.progressive_strategy.execute_search(
                query=query,
                search_func=search_func,
                min_results=1,  # Try next strategy if no results
                max_results=config.max_results,
                deduplicate_func=dedupe_func
            )
            
            return results
        else:
            # Original implementation for non-progressive search
            # Build query variants if fallback enabled
            if config.enable_fallback:
                query_variants = self.query_builder.get_query_variants(query)
            else:
                # Build single query (code-aware is default in build_query)
                query_variants = [self.query_builder.build_query(query)]
            
            results = []
            seen_paths = set()
            
            for variant in query_variants:
                try:
                    # Execute metadata search
                    variant_results = self.storage.search_files(
                        query=variant,
                        dataset_id=dataset_id,
                        limit=config.max_results,
                        timeout_ms=config.query_timeout_ms
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
                        
                except Exception as e:
                    logger.error(f"Search failed for query variant '{variant}': {e}", exc_info=True)
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
        
        # Analyze query complexity if enabled
        if config.enable_complexity_analysis:
            # Configure analyzer with current config settings
            self.query_analyzer.max_terms = config.max_query_terms
            self.query_analyzer.max_cost = config.max_query_cost
            metrics = self.query_analyzer.analyze(query)
            
            if metrics.complexity_level == ComplexityLevel.TOO_COMPLEX:
                logger.warning(
                    f"Query too complex: {', '.join(metrics.warnings)}"
                )
                # Optionally return empty results or raise exception
                return []
            elif metrics.warnings:
                logger.info(f"Query complexity warnings: {', '.join(metrics.warnings)}")
        
        # Sanitize query if enabled
        if config.enable_query_sanitization:
            try:
                # Use injected sanitizer, update config if needed
                if config.sanitization_config:
                    self.query_sanitizer.config = config.sanitization_config
                query = self.query_sanitizer.sanitize(query)
                logger.debug(f"Sanitized query: {query}")
            except ValueError as e:
                logger.warning(f"Query sanitization failed: {e}")
                # Return empty results for invalid queries
                return []
        
        # Use progressive search if enabled
        if config.enable_progressive_search and config.enable_fallback:
            # Define search function for progressive strategy
            def search_func(transformed_query: str) -> List[SearchResult]:
                results = self.storage.search_full_content(
                    query=transformed_query,
                    dataset_id=dataset_id,
                    limit=config.max_results,
                    include_snippets=config.enable_snippet_generation,
                    timeout_ms=config.query_timeout_ms
                )
                
                # Apply relevance filter if enabled
                if config.enable_relevance_scoring and config.min_relevance_score > 0:
                    results = [
                        r for r in results 
                        if r.relevance_score >= config.min_relevance_score
                    ]
                
                return results
            
            # Define deduplication function if needed
            dedupe_func = (
                lambda r: (r.file_path, r.match_content)
            ) if config.deduplicate_results else None
            
            # Execute progressive search
            results = self.progressive_strategy.execute_search(
                query=query,
                search_func=search_func,
                min_results=1,  # Try next strategy if no results
                max_results=config.max_results,
                deduplicate_func=dedupe_func
            )
            
            return results
        else:
            # Original implementation for non-progressive search
            # Build query variants if fallback enabled
            if config.enable_fallback:
                query_variants = self.query_builder.get_query_variants(query)
            else:
                # Build single query (code-aware is default in build_query)
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
                        include_snippets=config.enable_snippet_generation,
                        timeout_ms=config.query_timeout_ms
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
                        
                except Exception as e:
                    logger.error(f"Search failed for query variant '{variant}': {e}", exc_info=True)
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