# PR4: Search Service Implementation - Revised Design

## Overview
Based on comprehensive zen review feedback, this revised design addresses security vulnerabilities, performance concerns, and architectural improvements for the Search Service implementation.

## Key Design Changes

### 1. Unified Interface
Single search method instead of three separate methods:
```python
class SearchServiceInterface(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        dataset_id: str,
        config: Optional[SearchConfig] = None
    ) -> List[SearchResult]:
        """Execute search based on configuration."""
        pass
```

### 2. Consistent Return Type
Always return `List[SearchResult]`:
- Metadata-only results have `snippet=None`, `match_type="metadata"`
- Content results include snippets and `match_type="content"`
- Unified results combine both with appropriate scoring

### 3. Robust Query Sanitization

```python
class FTS5QuerySanitizer:
    """Secure FTS5 query sanitization with whitelist approach."""
    
    FTS5_OPERATORS = {'AND', 'OR', 'NOT'}
    FTS5_NEAR_PATTERN = re.compile(r'NEAR\s*\([^)]+\)', re.IGNORECASE)
    FTS5_SPECIAL_CHARS = {'"', '(', ')', '^', '*', '{', '}', ':', '[', ']', '-'}
    QUOTED_PHRASE_PATTERN = re.compile(r'"((?:[^"]|"")*)"')
    
    def sanitize_query(self, user_query: str) -> str:
        """
        Sanitize user query to prevent FTS5 injection.
        
        Strategy:
        1. Extract quoted phrases (preserve user intent)
        2. Process remaining tokens
        3. Wrap non-operator tokens in quotes
        4. Reconstruct query safely
        """
        # Extract quoted phrases
        phrases = []
        phrase_placeholders = []
        
        def phrase_replacer(match):
            phrase = match.group(1)
            # Double internal quotes for FTS5
            safe_phrase = phrase.replace('"', '""')
            phrases.append(f'"{safe_phrase}"')
            placeholder = f"__PHRASE_{len(phrases)-1}__"
            phrase_placeholders.append(placeholder)
            return placeholder
        
        # Replace phrases with placeholders
        query_without_phrases = self.QUOTED_PHRASE_PATTERN.sub(
            phrase_replacer, user_query
        )
        
        # Extract NEAR clauses
        near_clauses = []
        near_placeholders = []
        
        def near_replacer(match):
            near_clauses.append(match.group(0))
            placeholder = f"__NEAR_{len(near_clauses)-1}__"
            near_placeholders.append(placeholder)
            return placeholder
        
        query_without_near = self.FTS5_NEAR_PATTERN.sub(
            near_replacer, query_without_phrases
        )
        
        # Tokenize remaining query
        tokens = query_without_near.split()
        safe_tokens = []
        
        for token in tokens:
            # Skip placeholders
            if token in phrase_placeholders or token in near_placeholders:
                safe_tokens.append(token)
                continue
            
            # Preserve standalone operators
            if token.upper() in self.FTS5_OPERATORS:
                safe_tokens.append(token.upper())
                continue
            
            # Quote everything else to neutralize special chars
            # This prevents injection of column filters, wildcards, etc.
            escaped_token = token.replace('"', '""')
            safe_tokens.append(f'"{escaped_token}"')
        
        # Reconstruct query
        safe_query = " ".join(safe_tokens)
        
        # Replace placeholders with safe content
        for i, placeholder in enumerate(phrase_placeholders):
            safe_query = safe_query.replace(placeholder, phrases[i])
        
        for i, placeholder in enumerate(near_placeholders):
            safe_query = safe_query.replace(placeholder, near_clauses[i])
        
        return safe_query
```

### 4. Progressive Enhancement Search Strategy

```python
class ProgressiveSearchStrategy:
    """Execute searches progressively for optimal performance."""
    
    def execute_search(
        self,
        query_builder: FTS5QueryBuilder,
        storage: StorageBackend,
        query: str,
        dataset_id: str,
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        Progressive search execution:
        1. Try primary query first
        2. If insufficient results, execute combined fallback
        3. Combine and deduplicate results
        """
        results = []
        min_results_threshold = config.get('min_results_threshold', 10)
        
        # Step 1: Execute primary query
        primary_query = query_builder.build_query(query)
        primary_results = storage.search_unified(
            content_query=primary_query,
            metadata_query=primary_query,
            dataset_id=dataset_id,
            limit=config.max_results,
            deduplicate=DeduplicationStrategy.BY_FILEPATH
        )
        
        results.extend(primary_results)
        
        # Step 2: Check if we need fallback
        if len(results) < min_results_threshold and config.enable_fallback:
            # Get fallback variants
            variants = query_builder.get_query_variants(query)
            fallback_queries = variants[1:]  # Skip primary
            
            if fallback_queries:
                # Combine fallbacks into single OR query
                combined_fallback = " OR ".join(
                    f"({q})" for q in fallback_queries
                )
                
                fallback_results = storage.search_unified(
                    content_query=combined_fallback,
                    metadata_query=combined_fallback,
                    dataset_id=dataset_id,
                    limit=config.max_results - len(results),
                    deduplicate=DeduplicationStrategy.BY_FILEPATH
                )
                
                # Merge results, avoiding duplicates
                seen_paths = {r.file_path for r in results}
                for result in fallback_results:
                    if result.file_path not in seen_paths:
                        results.append(result)
                        seen_paths.add(result.file_path)
        
        # Step 3: Apply relevance filtering if enabled
        if config.enable_relevance_scoring and config.min_relevance_score > 0:
            results = [
                r for r in results 
                if r.relevance_score >= config.min_relevance_score
            ]
        
        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        
        return results[:config.max_results]
```

### 5. Enhanced Storage Backend Interface

```python
from enum import Enum

class DeduplicationStrategy(Enum):
    NONE = "none"
    BY_FILEPATH = "by_filepath"

class StorageBackend(ABC):
    """Enhanced storage backend with unified search support."""
    
    @abstractmethod
    def search_unified(
        self,
        content_query: str,
        metadata_query: str,
        dataset_id: str,
        limit: int,
        deduplicate: DeduplicationStrategy = DeduplicationStrategy.BY_FILEPATH,
        timeout_seconds: float = 30.0
    ) -> List[SearchResult]:
        """
        Execute unified search with database-level deduplication.
        
        Args:
            content_query: FTS5 query for content search
            metadata_query: FTS5 query for metadata search
            dataset_id: Dataset to search in
            limit: Maximum results
            deduplicate: Deduplication strategy
            timeout_seconds: Query timeout
            
        Returns:
            Combined, deduplicated search results
        """
        pass
```

### 6. Query Timeout Implementation

```python
class SqliteBackend(StorageBackend):
    """SQLite implementation with timeout support."""
    
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool = ConnectionPool(db_path, pool_size)
    
    def search_unified(
        self,
        content_query: str,
        metadata_query: str,
        dataset_id: str,
        limit: int,
        deduplicate: DeduplicationStrategy = DeduplicationStrategy.BY_FILEPATH,
        timeout_seconds: float = 30.0
    ) -> List[SearchResult]:
        """Execute unified search with timeout protection."""
        conn = self.pool.get_connection()
        
        try:
            # Set busy timeout for lock contention
            conn.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
            
            # Set progress handler for query timeout
            # Check every 10000 VM instructions
            start_time = time.time()
            
            def check_timeout():
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    return 1  # Non-zero interrupts query
                return 0
            
            conn.set_progress_handler(check_timeout, 10000)
            
            # Execute unified search query
            if deduplicate == DeduplicationStrategy.BY_FILEPATH:
                query = self._build_deduplicated_query(
                    content_query, metadata_query, dataset_id, limit
                )
            else:
                query = self._build_union_query(
                    content_query, metadata_query, dataset_id, limit
                )
            
            cursor = conn.cursor()
            cursor.execute(query)
            results = self._parse_results(cursor.fetchall())
            
            return results
            
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e):
                raise QueryTimeoutError(
                    f"Search query timed out after {timeout_seconds}s"
                )
            raise
        finally:
            # Clear progress handler
            conn.set_progress_handler(None)
            self.pool.release_connection(conn)
    
    def _build_deduplicated_query(
        self, content_query: str, metadata_query: str, 
        dataset_id: str, limit: int
    ) -> str:
        """Build query with database-level deduplication."""
        return f"""
        WITH ranked_results AS (
            SELECT 
                file_path,
                dataset_id,
                match_content,
                match_type,
                snippet,
                relevance_score,
                ROW_NUMBER() OVER (
                    PARTITION BY file_path 
                    ORDER BY relevance_score DESC
                ) as rn
            FROM (
                -- Content search
                SELECT 
                    c.file_path,
                    c.dataset_id,
                    c.content as match_content,
                    'content' as match_type,
                    snippet(file_content_fts, 1, '<b>', '</b>', '...', 64) as snippet,
                    -bm25(file_content_fts) as relevance_score
                FROM file_content_fts
                JOIN file_content c ON c.id = file_content_fts.rowid
                WHERE file_content_fts MATCH ?
                AND c.dataset_id = ?
                
                UNION ALL
                
                -- Metadata search
                SELECT 
                    m.file_path,
                    m.dataset_id,
                    m.overview as match_content,
                    'metadata' as match_type,
                    NULL as snippet,
                    -bm25(file_metadata_fts) * 0.8 as relevance_score
                FROM file_metadata_fts
                JOIN file_metadata m ON m.id = file_metadata_fts.rowid
                WHERE file_metadata_fts MATCH ?
                AND m.dataset_id = ?
            )
        )
        SELECT * FROM ranked_results 
        WHERE rn = 1
        ORDER BY relevance_score DESC
        LIMIT ?
        """
```

### 7. Query Complexity Analysis

```python
class QueryComplexityAnalyzer:
    """Analyze query complexity to prevent DoS attacks."""
    
    MAX_WILDCARDS = 3
    MAX_TERMS = 20
    MAX_NEAR_CLAUSES = 3
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """Analyze query complexity metrics."""
        wildcards = query.count('*')
        terms = len(query.split())
        near_clauses = len(re.findall(r'NEAR\s*\(', query, re.IGNORECASE))
        
        return {
            'wildcards': wildcards,
            'terms': terms,
            'near_clauses': near_clauses,
            'is_complex': (
                wildcards > self.MAX_WILDCARDS or
                terms > self.MAX_TERMS or
                near_clauses > self.MAX_NEAR_CLAUSES
            )
        }
    
    def validate_query(self, query: str) -> None:
        """Validate query complexity, raise if too complex."""
        analysis = self.analyze_query(query)
        
        if analysis['is_complex']:
            raise QueryTooComplexError(
                f"Query exceeds complexity limits: "
                f"{analysis['wildcards']} wildcards (max {self.MAX_WILDCARDS}), "
                f"{analysis['terms']} terms (max {self.MAX_TERMS}), "
                f"{analysis['near_clauses']} NEAR clauses (max {self.MAX_NEAR_CLAUSES})"
            )
```

## Testing Strategy

1. **Unit Tests**:
   - Test sanitizer with injection attempts
   - Test progressive search logic
   - Test complexity analyzer
   - Mock storage backend for isolation

2. **Integration Tests**:
   - Test with real SQLite backend
   - Test timeout behavior
   - Test deduplication strategies
   - Test concurrent access

3. **Security Tests**:
   - FTS5 injection attempts
   - DoS via complex queries
   - Timeout enforcement
   - Resource exhaustion

## Implementation Order

1. Implement FTS5QuerySanitizer with comprehensive tests
2. Update StorageBackend interface with unified search
3. Implement timeout handling in SqliteBackend
4. Build SearchService with progressive strategy
5. Add query complexity analysis
6. Comprehensive security testing

## Key Benefits of Revised Design

1. **Security**: Robust sanitization prevents FTS5 injection
2. **Performance**: Progressive search minimizes latency
3. **Reliability**: Timeouts prevent resource exhaustion
4. **Simplicity**: Single search method, consistent return type
5. **Scalability**: Database-level deduplication
6. **Maintainability**: Clear separation of concerns