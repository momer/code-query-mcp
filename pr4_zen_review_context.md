# PR4: Search Service Implementation - Zen Review Context

## Overview
We're about to implement PR4: Search Service with dependency injection and feature flags. This builds on top of the completed PRs:
- PR1: Fixed FTS5 tokenizer issues and unified query processing
- PR2: Created StorageBackend interface and SqliteBackend implementation  
- PR3: Implemented FTS5QueryBuilder with strategy pattern

## Objectives for PR4
1. Create a SearchService that encapsulates all search logic
2. Use dependency injection for QueryBuilder and StorageBackend
3. Implement feature flags for configurable search behavior
4. Support different search modes (unified, metadata-only, content-only)
5. Provide clean separation between search logic and storage

## Proposed Architecture

### SearchService Interface
```python
class SearchServiceInterface(ABC):
    @abstractmethod
    def search(query: str, dataset_id: str, config: SearchConfig) -> List[SearchResult]
    @abstractmethod
    def search_metadata(query: str, dataset_id: str, config: SearchConfig) -> List[FileMetadata]
    @abstractmethod
    def search_content(query: str, dataset_id: str, config: SearchConfig) -> List[SearchResult]
```

### Feature Flags via SearchConfig
```python
@dataclass
class SearchConfig:
    enable_fallback: bool = True
    enable_code_aware: bool = True
    enable_snippet_generation: bool = True
    enable_relevance_scoring: bool = True
    max_results: int = 50
    snippet_context_chars: int = 64
    min_relevance_score: float = 0.0
    search_mode: SearchMode = SearchMode.UNIFIED
    deduplicate_results: bool = True
```

### Search Modes
- UNIFIED: Combines metadata and content search with deduplication
- METADATA_ONLY: Only searches file metadata (overview, functions, etc.)
- CONTENT_ONLY: Only searches file content with snippets

### Dependency Injection
```python
class SearchService(SearchServiceInterface):
    def __init__(
        self,
        storage_backend: StorageBackend,
        query_builder: Optional[FTS5QueryBuilder] = None,
        default_config: Optional[SearchConfig] = None
    ):
        self.storage = storage_backend
        self.query_builder = query_builder or FTS5QueryBuilder()
        self.default_config = default_config or SearchConfig()
```

## Implementation Plan
1. Create SearchService with the interface and implementation
2. Inject FTS5QueryBuilder for query building
3. Inject StorageBackend for executing searches
4. Implement fallback search using query variants
5. Add deduplication logic for unified search
6. Support relevance scoring and filtering
7. Handle errors gracefully with fallback variants

## Integration Points
- The SearchService will be used by MCP tools instead of direct storage calls
- CodeQueryServer will create SearchService with injected dependencies
- Feature flags allow runtime configuration of search behavior

## Key Design Decisions
1. **Fallback Strategy**: Use QueryBuilder.get_query_variants() for progressive search
2. **Deduplication**: Track seen file paths and content to avoid duplicates
3. **Error Handling**: Continue with next variant if one fails
4. **Unified Search**: Prioritize content results (with snippets) over metadata-only
5. **Relevance Filtering**: Optional minimum score threshold

## Testing Strategy
1. Unit tests with mocked StorageBackend
2. Test each search mode independently
3. Test feature flag combinations
4. Test fallback behavior and error handling
5. Integration tests with real SqliteBackend

## Questions for Review
1. Is the SearchConfig comprehensive enough for future needs?
2. Should we add caching at the SearchService level?
3. Is the deduplication strategy appropriate?
4. Should we add search result ranking/re-ordering capabilities?
5. Do we need additional search modes or is the current set sufficient?

## Related Code Context

### Current Storage Interface (from PR2)
The StorageBackend interface defines these search methods that SearchService will use:
- `search_files(query, dataset_id, limit)` -> List[FileMetadata]
- `search_full_content(query, dataset_id, limit, include_snippets)` -> List[SearchResult]

### Current QueryBuilder (from PR3)
The FTS5QueryBuilder provides:
- `build_query(user_query)` -> str (primary query)
- `build_fallback_query(user_query)` -> str (fallback query)
- `get_query_variants(user_query)` -> List[str] (multiple variants)

### Models
- FileMetadata: Contains file overview, functions, imports, exports
- SearchResult: Contains match content, snippet, relevance score, metadata

## Potential Concerns
1. **Performance**: Multiple query variants could impact performance
2. **Memory**: Deduplication tracking could use significant memory for large result sets
3. **Complexity**: Feature flags add configuration complexity
4. **Testing**: Many flag combinations to test

Please review this design and provide feedback on:
1. Architecture appropriateness
2. Missing features or concerns
3. Potential bugs or edge cases
4. Performance implications
5. Testing completeness