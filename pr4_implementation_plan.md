# PR 4: Extract Search Service with Dependency Injection and Feature Flag

## Overview
This PR extracts search functionality into a dedicated service with dependency injection and feature flag support. It consolidates all search logic, provides a clean API, and enables gradual rollout through feature flags.

**Size**: Medium | **Risk**: Medium | **Value**: High

## Dependencies
- PR 2 must be completed (needs StorageBackend interface)
- PR 3 must be completed (needs FTS5QueryBuilder)
- This PR blocks PR 6 (Application Layer needs SearchService)

## Objectives
1. Extract all search logic into a dedicated SearchService
2. Implement dependency injection for flexibility
3. Add feature flag for gradual rollout
4. Provide unified search API with automatic fallback
5. Enable search result caching and optimization

## Implementation Steps

### Step 1: Create Search Service Structure
```
services/
├── __init__.py              # Export SearchService
├── search_service.py        # Main search service implementation
├── search_cache.py          # LRU cache for search results
├── search_metrics.py        # Search performance tracking
└── feature_flags.py         # Feature flag implementation
```

### Step 2: Define Feature Flag System
**File**: `services/feature_flags.py`
- Simple environment-based flags initially
- Percentage-based rollout support
- Runtime toggle capability
- Clear flag naming convention

### Step 3: Implement Search Service Interface
**File**: `services/search_service.py`
- Clean public API for all search operations
- Dependency injection for storage and query builder
- Automatic fallback handling
- Result ranking and deduplication
- Performance metrics collection

### Step 4: Add Search Result Caching
**File**: `services/search_cache.py`
- LRU cache for recent searches
- Cache key normalization
- TTL-based expiration
- Cache hit/miss metrics

### Step 5: Implement Search Metrics
**File**: `services/search_metrics.py`
- Query execution time tracking
- Result count statistics
- Fallback usage tracking
- Cache performance metrics

### Step 6: Application Layer Integration
- Create application factory or startup script
- Wire dependencies at application level
- Feature flag controls old vs new implementation
- Avoid circular dependencies

## Detailed Implementation

### services/feature_flags.py
```python
import os
import random
from typing import Dict, Any, Optional
from dataclasses import dataclass
import json
import logging

logger = logging.getLogger(__name__)

@dataclass
class FeatureFlag:
    """Configuration for a feature flag."""
    name: str
    enabled: bool = False
    percentage: int = 0  # 0-100 for gradual rollout
    metadata: Dict[str, Any] = None

class FeatureFlagService:
    """Simple feature flag service with environment variable support."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize feature flags from environment or config file.
        
        Args:
            config_path: Optional path to JSON config file
        """
        self._flags: Dict[str, FeatureFlag] = {}
        self._load_defaults()
        
        if config_path and os.path.exists(config_path):
            self._load_from_file(config_path)
        
        self._load_from_env()
    
    def _load_defaults(self):
        """Load default feature flags."""
        self._flags = {
            'use_search_service': FeatureFlag(
                name='use_search_service',
                enabled=False,
                percentage=0,
                metadata={'description': 'Use new SearchService for all searches'}
            ),
            'enable_search_cache': FeatureFlag(
                name='enable_search_cache',
                enabled=True,
                percentage=100,
                metadata={'description': 'Cache search results for performance'}
            ),
            'collect_search_metrics': FeatureFlag(
                name='collect_search_metrics',
                enabled=True,
                percentage=100,
                metadata={'description': 'Collect search performance metrics'}
            ),
        }
    
    def _load_from_env(self):
        """Override flags from environment variables."""
        # Check for specific flag overrides
        for flag_name in self._flags:
            env_key = f'FEATURE_{flag_name.upper()}'
            if env_key in os.environ:
                value = os.environ[env_key].lower()
                if value in ('true', '1', 'on'):
                    self._flags[flag_name].enabled = True
                    self._flags[flag_name].percentage = 100
                elif value in ('false', '0', 'off'):
                    self._flags[flag_name].enabled = False
                    self._flags[flag_name].percentage = 0
                elif value.endswith('%'):
                    # Support percentage rollout
                    try:
                        pct = int(value[:-1])
                        self._flags[flag_name].enabled = True
                        self._flags[flag_name].percentage = max(0, min(100, pct))
                    except ValueError:
                        pass
    
    def _load_from_file(self, config_path: str):
        """Load flags from JSON config file."""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                for flag_name, flag_config in config.items():
                    if flag_name in self._flags:
                        self._flags[flag_name].enabled = flag_config.get('enabled', False)
                        self._flags[flag_name].percentage = flag_config.get('percentage', 0)
        except Exception as e:
            # Log error but continue with defaults
            logger.error(f"Failed to load feature flag config from {config_path}: {e}")
    
    def is_enabled(self, flag_name: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Check if a feature flag is enabled.
        
        Args:
            flag_name: Name of the feature flag
            context: Optional context for percentage-based rollout (e.g., user_id)
            
        Returns:
            True if feature is enabled for this request
        """
        if flag_name not in self._flags:
            return False
        
        flag = self._flags[flag_name]
        
        if not flag.enabled:
            return False
        
        if flag.percentage >= 100:
            return True
        
        if flag.percentage <= 0:
            return False
        
        # Percentage-based rollout
        if context and 'request_id' in context:
            # Deterministic rollout based on a stable request identifier
            import hashlib
            identifier = f"{flag_name}:{context['request_id']}".encode('utf-8')
            hash_value = int(hashlib.sha1(identifier).hexdigest(), 16) % 100
            return hash_value < flag.percentage
        elif context and 'user_id' in context:
            # Deterministic rollout based on user ID using stable hash
            import hashlib
            identifier = f"{flag_name}:{context['user_id']}".encode('utf-8')
            hash_value = int(hashlib.sha1(identifier).hexdigest(), 16) % 100
            return hash_value < flag.percentage
        else:
            # No stable context - log warning
            logger.warning(f"Feature flag '{flag_name}' checked without stable context. This can lead to inconsistent behavior.")
            return False  # Default to disabled without stable context
    
    def get_all_flags(self) -> Dict[str, Dict[str, Any]]:
        """Get all feature flags and their current state."""
        return {
            name: {
                'enabled': flag.enabled,
                'percentage': flag.percentage,
                'metadata': flag.metadata
            }
            for name, flag in self._flags.items()
        }

# Global instance
_feature_flags = None

def get_feature_flags() -> FeatureFlagService:
    """Get or create the global feature flag service."""
    global _feature_flags
    if _feature_flags is None:
        config_path = os.environ.get('FEATURE_FLAGS_CONFIG')
        _feature_flags = FeatureFlagService(config_path)
    return _feature_flags
```

### services/search_service.py
```python
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
import logging
import time

from storage.backend import StorageBackend
from storage.models import SearchResult
from search.query_builder import FTS5QueryBuilder
from .search_cache import SearchCache
from .search_metrics import SearchMetrics
from .feature_flags import get_feature_flags

logger = logging.getLogger(__name__)

@dataclass
class SearchOptions:
    """Options for search operations."""
    limit: int = 10
    use_cache: bool = True
    include_content: bool = True
    enable_fallback: bool = True
    max_fallback_attempts: int = 3

class SearchService:
    """
    High-level search service with caching, metrics, and fallback support.
    """
    
    def __init__(self, 
                 storage: StorageBackend,
                 query_builder: Optional[FTS5QueryBuilder] = None,
                 cache: Optional[SearchCache] = None,
                 metrics: Optional[SearchMetrics] = None):
        """
        Initialize search service with dependencies.
        
        Args:
            storage: Storage backend for data access
            query_builder: Query builder for FTS5 queries
            cache: Optional cache for search results
            metrics: Optional metrics collector
        """
        self.storage = storage
        self.query_builder = query_builder or FTS5QueryBuilder()
        self.cache = cache or SearchCache()
        self.metrics = metrics or SearchMetrics()
        self.feature_flags = get_feature_flags()
    
    def search(self, query: str, dataset: str, options: Optional[SearchOptions] = None) -> List[SearchResult]:
        """
        Perform a search with automatic fallback and caching.
        
        Args:
            query: User search query
            dataset: Dataset to search in
            options: Search options
            
        Returns:
            List of search results
        """
        options = options or SearchOptions()
        start_time = time.time()
        cache_key = None  # Initialize cache_key
        
        # Check cache first
        if options.use_cache and self.feature_flags.is_enabled('enable_search_cache'):
            cache_key = self._get_cache_key(query, dataset, options)
            cached_results = self.cache.get(cache_key)
            if cached_results is not None:
                self.metrics.record_cache_hit()
                return cached_results
            else:
                self.metrics.record_cache_miss()
        
        # Build query variants for progressive search
        query_variants = self.query_builder.get_query_variants(query)
        
        results = []
        fallback_count = 0
        
        for i, fts_query in enumerate(query_variants):
            if i > 0:
                fallback_count += 1
                if not options.enable_fallback or fallback_count > options.max_fallback_attempts:
                    break
            
            # Try unified search first
            try:
                results = self.storage.search_unified(fts_query, dataset, options.limit)
                if results:
                    break
            except Exception as e:
                logger.error(f"Search failed for query variant {i}: {e}")
                continue
        
        # Post-process results
        results = self._post_process_results(results, query, options)
        
        # Cache results
        if cache_key:  # Check if a key was generated
            self.cache.set(cache_key, results)
        
        # Record metrics
        if self.feature_flags.is_enabled('collect_search_metrics'):
            elapsed = time.time() - start_time
            self.metrics.record_search(
                query=query,
                dataset=dataset,
                result_count=len(results),
                elapsed_time=elapsed,
                fallback_count=fallback_count
            )
        
        return results
    
    def search_metadata(self, query: str, dataset: str, options: Optional[SearchOptions] = None) -> List[SearchResult]:
        """
        Search only metadata fields (overview, function names, etc).
        
        Args:
            query: User search query
            dataset: Dataset to search in
            options: Search options
            
        Returns:
            List of search results from metadata
        """
        options = options or SearchOptions()
        fts_query = self.query_builder.build_query(query)
        
        try:
            results = self.storage.search_metadata(fts_query, dataset, options.limit)
            return self._post_process_results(results, query, options)
        except Exception as e:
            logger.error(f"Metadata search failed: {e}")
            return []
    
    def search_content(self, query: str, dataset: str, options: Optional[SearchOptions] = None) -> List[SearchResult]:
        """
        Search full file content.
        
        Args:
            query: User search query
            dataset: Dataset to search in
            options: Search options
            
        Returns:
            List of search results from content
        """
        options = options or SearchOptions()
        fts_query = self.query_builder.build_query(query)
        
        try:
            results = self.storage.search_content(fts_query, dataset, options.limit)
            return self._post_process_results(results, query, options)
        except Exception as e:
            logger.error(f"Content search failed: {e}")
            return []
    
    def _get_cache_key(self, query: str, dataset: str, options: SearchOptions) -> str:
        """Generate cache key for search."""
        # Normalize query for caching
        normalized_query = ' '.join(query.lower().split())
        return f"{dataset}:{normalized_query}:{options.limit}:{options.include_content}"
    
    def _post_process_results(self, results: List[SearchResult], query: str, options: SearchOptions) -> List[SearchResult]:
        """Post-process search results."""
        # Remove content if not requested
        if not options.include_content:
            for result in results:
                if hasattr(result, 'full_content'):
                    result.full_content = None
        
        # Additional ranking/filtering could go here
        
        return results
    
    def get_search_suggestions(self, partial_query: str, dataset: str, limit: int = 5) -> List[str]:
        """
        Get search suggestions based on partial query.
        
        Args:
            partial_query: Partial search query
            dataset: Dataset to search in
            limit: Maximum suggestions
            
        Returns:
            List of suggested search terms
        """
        # Simple implementation - could be enhanced with:
        # - Recent searches
        # - Popular searches
        # - Completion from indexed terms
        
        recent_searches = self.cache.get_recent_queries(dataset)
        suggestions = []
        
        partial_lower = partial_query.lower()
        for recent in recent_searches:
            if recent.lower().startswith(partial_lower) and recent not in suggestions:
                suggestions.append(recent)
                if len(suggestions) >= limit:
                    break
        
        return suggestions
```

### services/search_cache.py
```python
from typing import List, Optional, Any, Tuple
from collections import OrderedDict
import time
import hashlib

from storage.models import SearchResult

class SearchCache:
    """LRU cache for search results with TTL support."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Initialize search cache.
        
        Args:
            max_size: Maximum number of cached searches
            ttl_seconds: Time-to-live for cache entries
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Tuple[List[SearchResult], float]] = OrderedDict()
        self._recent_queries: OrderedDict[str, List[str]] = OrderedDict()  # dataset -> queries
    
    def get(self, key: str) -> Optional[List[SearchResult]]:
        """
        Get cached search results.
        
        Args:
            key: Cache key
            
        Returns:
            Cached results or None if not found/expired
        """
        if key not in self._cache:
            return None
        
        results, timestamp = self._cache[key]
        
        # Check TTL
        if time.time() - timestamp > self.ttl_seconds:
            del self._cache[key]
            return None
        
        # Move to end (LRU)
        self._cache.move_to_end(key)
        return results
    
    def set(self, key: str, results: List[SearchResult]):
        """
        Cache search results.
        
        Args:
            key: Cache key
            results: Search results to cache
        """
        # Extract dataset from key for recent queries
        dataset = key.split(':')[0]
        query = key.split(':')[1]
        
        # Update recent queries
        if dataset not in self._recent_queries:
            self._recent_queries[dataset] = []
        
        if query not in self._recent_queries[dataset]:
            self._recent_queries[dataset].append(query)
            # Keep only last 20 queries per dataset
            if len(self._recent_queries[dataset]) > 20:
                self._recent_queries[dataset].pop(0)
        
        # Add to cache
        self._cache[key] = (results, time.time())
        
        # Evict oldest if over capacity
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)
    
    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()
        self._recent_queries.clear()
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_entries = len(self._cache)
        
        # Calculate memory usage (approximate)
        memory_bytes = 0
        for results, _ in self._cache.values():
            memory_bytes += sum(
                len(str(r.to_dict())) for r in results
            )
        
        return {
            'total_entries': total_entries,
            'memory_bytes': memory_bytes,
            'max_size': self.max_size,
            'ttl_seconds': self.ttl_seconds
        }
    
    def get_recent_queries(self, dataset: str) -> List[str]:
        """Get recent queries for a dataset."""
        return self._recent_queries.get(dataset, [])
```

### services/search_metrics.py
```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import statistics
import threading

@dataclass
class SearchMetricEntry:
    """Single search metric entry."""
    query: str
    dataset: str
    result_count: int
    elapsed_time: float
    fallback_count: int
    timestamp: datetime = field(default_factory=datetime.now)

class SearchMetrics:
    """Thread-safe collector and reporter of search performance metrics."""
    
    def __init__(self, max_entries: int = 10000):
        """
        Initialize metrics collector.
        
        Args:
            max_entries: Maximum metrics entries to keep
        """
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._metrics: List[SearchMetricEntry] = []
        self._cache_hits = 0
        self._cache_misses = 0
    
    def record_search(self, query: str, dataset: str, result_count: int, 
                     elapsed_time: float, fallback_count: int):
        """Record a search operation."""
        entry = SearchMetricEntry(
            query=query,
            dataset=dataset,
            result_count=result_count,
            elapsed_time=elapsed_time,
            fallback_count=fallback_count
        )
        
        with self._lock:
            self._metrics.append(entry)
            
            # Trim old entries
            if len(self._metrics) > self.max_entries:
                self._metrics = self._metrics[-self.max_entries:]
    
    def record_cache_hit(self):
        """Record a cache hit."""
        with self._lock:
            self._cache_hits += 1
    
    def record_cache_miss(self):
        """Record a cache miss."""
        with self._lock:
            self._cache_misses += 1
    
    def get_summary(self, dataset: Optional[str] = None) -> Dict[str, any]:
        """
        Get metrics summary.
        
        Args:
            dataset: Optional dataset filter
            
        Returns:
            Summary statistics
        """
        with self._lock:
            # Create copies to analyze outside the lock
            metrics = list(self._metrics)
            cache_hits = self._cache_hits
            cache_misses = self._cache_misses
        
        # Filter outside the lock
        if dataset:
            metrics = [m for m in metrics if m.dataset == dataset]
        
        if not metrics:
            return {
                'total_searches': 0,
                'cache_hit_rate': 0.0
            }
        
        elapsed_times = [m.elapsed_time for m in metrics]
        result_counts = [m.result_count for m in metrics]
        fallback_counts = [m.fallback_count for m in metrics]
        
        total_cache_requests = cache_hits + cache_misses
        cache_hit_rate = cache_hits / total_cache_requests if total_cache_requests > 0 else 0.0
        
        return {
            'total_searches': len(metrics),
            'avg_elapsed_time': statistics.mean(elapsed_times),
            'p95_elapsed_time': statistics.quantiles(elapsed_times, n=20)[18] if len(elapsed_times) > 20 else max(elapsed_times, default=0),
            'avg_result_count': statistics.mean(result_counts),
            'searches_with_fallback': sum(1 for m in metrics if m.fallback_count > 0),
            'avg_fallback_count': statistics.mean(fallback_counts),
            'cache_hit_rate': cache_hit_rate,
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses
        }
    
    def get_slow_queries(self, threshold: float = 1.0, limit: int = 10) -> List[SearchMetricEntry]:
        """Get slowest queries above threshold."""
        slow_queries = [m for m in self._metrics if m.elapsed_time > threshold]
        slow_queries.sort(key=lambda x: x.elapsed_time, reverse=True)
        return slow_queries[:limit]
    
    def get_popular_queries(self, dataset: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most popular queries."""
        if dataset:
            metrics = [m for m in self._metrics if m.dataset == dataset]
        else:
            metrics = self._metrics
        
        query_counts: Dict[str, int] = {}
        for m in metrics:
            query_counts[m.query] = query_counts.get(m.query, 0) + 1
        
        popular = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)
        return popular[:limit]
```

## Testing Plan

### Unit Tests

#### test_feature_flags.py
```python
def test_feature_flag_basic():
    """Test basic feature flag functionality."""
    flags = FeatureFlagService()
    assert not flags.is_enabled('use_search_service')
    
def test_feature_flag_percentage():
    """Test percentage-based rollout."""
    flags = FeatureFlagService()
    # Test deterministic rollout with context
    
def test_feature_flag_env_override():
    """Test environment variable overrides."""
    os.environ['FEATURE_USE_SEARCH_SERVICE'] = 'true'
    flags = FeatureFlagService()
    assert flags.is_enabled('use_search_service')
```

#### test_search_service.py
```python
def test_search_with_fallback():
    """Test search with automatic fallback."""
    mock_storage = Mock(StorageBackend)
    mock_storage.search_unified.side_effect = [[], mock_results]  # First fails, second succeeds
    
    service = SearchService(mock_storage)
    results = service.search("test query", "dataset")
    assert len(results) > 0
    assert mock_storage.search_unified.call_count == 2

def test_search_caching():
    """Test search result caching."""
    service = SearchService(mock_storage)
    
    # First search - cache miss
    results1 = service.search("test", "dataset")
    
    # Second search - cache hit
    results2 = service.search("test", "dataset")
    
    assert results1 == results2
    assert mock_storage.search_unified.call_count == 1

def test_search_metrics_collection():
    """Test metrics are collected correctly."""
    service = SearchService(mock_storage)
    service.search("test", "dataset")
    
    metrics = service.metrics.get_summary()
    assert metrics['total_searches'] == 1
```

### Integration Tests
```python
def test_service_with_real_storage():
    """Test SearchService with real SqliteBackend."""
    
def test_feature_flag_gradual_rollout():
    """Test gradual rollout works correctly."""
    
def test_cache_performance():
    """Test cache improves performance."""
```

## Migration Strategy

### Phase 1: Deploy Behind Flag
1. Deploy SearchService with feature flag disabled
2. All searches continue using existing code
3. No user impact

### Phase 2: Internal Testing
1. Enable flag for internal testing (percentage = 5%)
2. Monitor metrics and logs
3. Compare results with existing implementation

### Phase 3: Gradual Rollout
1. Increase percentage gradually: 5% → 25% → 50% → 100%
2. Monitor performance metrics at each stage
3. Rollback capability via flag

### Phase 4: Cleanup
1. Once stable at 100%, remove old code paths
2. Remove feature flag checks
3. Optimize based on collected metrics

## Application Layer Integration

### Application Factory Pattern
```python
# app_factory.py or main.py
from storage.sqlite_backend import SqliteBackend
from services.search_service import SearchService, SearchOptions
from services.search_cache import SearchCache
from services.search_metrics import SearchMetrics
from services.feature_flags import get_feature_flags
from search.query_builder import FTS5QueryBuilder

class ApplicationContext:
    """Application context with dependency injection."""
    
    def __init__(self, db_path: str):
        self.feature_flags = get_feature_flags()
        
        # Create storage backend
        self.storage_backend = SqliteBackend(db_path)
        
        # Create search service with dependencies
        if self.feature_flags.is_enabled('use_search_service', {'request_id': 'startup'}):
            self.search_service = SearchService(
                storage=self.storage_backend,
                query_builder=FTS5QueryBuilder(),
                cache=SearchCache(),
                metrics=SearchMetrics()
            )
        else:
            self.search_service = None
        
        # Legacy storage for backward compatibility
        from storage.sqlite_storage import SqliteStorage
        self.legacy_storage = SqliteStorage(db_path)
    
    def search_files(self, query: str, dataset: str, limit: int = 10, request_id: str = None):
        """Route search to appropriate implementation."""
        context = {'request_id': request_id} if request_id else {}
        
        if self.search_service and self.feature_flags.is_enabled('use_search_service', context):
            options = SearchOptions(limit=limit)
            results = self.search_service.search_metadata(query, dataset, options)
            return [r.to_dict() for r in results]
        else:
            # Use legacy implementation
            return self.legacy_storage.search_files(query, dataset, limit)

# Usage in MCP server
app_context = ApplicationContext(db_path)
# Pass app_context to request handlers
```

## Performance Considerations

1. **Caching Strategy**:
   - LRU eviction for memory efficiency
   - TTL to handle data updates
   - Cache key normalization

2. **Metrics Overhead**:
   - Async metrics collection option
   - Sampling for high-traffic scenarios
   - Efficient storage of metric data

3. **Service Initialization**:
   - Lazy loading of dependencies
   - Connection pooling from StorageBackend
   - Warm cache on startup option

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cache invalidation issues | Stale results | TTL-based expiration, dataset versioning |
| Performance regression | Slower searches | Feature flag for quick rollback, metrics monitoring |
| Memory usage from cache | OOM errors | Configurable cache size, memory monitoring |
| Complex dependency graph | Hard to test | Clear interfaces, dependency injection |
| Metrics overhead | Performance impact | Sampling, async collection option |

## Success Criteria

1. **Functionality**:
   - All search methods work through service
   - Automatic fallback improves result quality
   - Cache improves response times

2. **Performance**:
   - P95 latency improves by 30% with cache
   - No regression for cache misses
   - Metrics collection < 1% overhead

3. **Reliability**:
   - Feature flag enables safe rollout
   - No data loss or corruption
   - Graceful degradation on errors

4. **Observability**:
   - Clear metrics on search performance
   - Cache hit rate > 30% in production
   - Slow query identification

## Documentation Updates

1. Document SearchService API
2. Feature flag configuration guide
3. Metrics interpretation guide
4. Cache tuning recommendations

## Review Checklist

- [ ] SearchService interface complete
- [ ] Dependency injection working
- [ ] Feature flags tested
- [ ] Cache implementation efficient
- [ ] Metrics provide actionable insights
- [ ] Integration preserves compatibility
- [ ] Tests cover edge cases
- [ ] Documentation complete