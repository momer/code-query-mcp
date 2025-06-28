# PR 4 Implementation Plan - Review Context

## Project Context
The Code Query MCP Server now has:
1. Fixed FTS5 tokenizer that preserves code tokens (PR 1 - complete)
2. Storage backend interface with DTOs (PR 2 - complete)  
3. Query builder with fallback support (PR 3 - complete)

PR 4 extracts search functionality into a dedicated service with dependency injection and feature flags for safe rollout.

## Problem Being Solved
- Search logic is scattered throughout sqlite_storage.py
- No caching layer for repeated searches
- Limited visibility into search performance
- Risky to make search improvements without gradual rollout
- No clear service boundary for search operations

## PR 4 Objectives
1. Extract all search logic into SearchService
2. Add dependency injection for flexibility
3. Implement feature flags for gradual rollout
4. Add caching layer for performance
5. Collect metrics for observability

## Key Design Decisions
1. **Service Pattern**: SearchService as the single entry point for all searches
2. **Feature Flags**: Environment-based with percentage rollout support
3. **LRU Cache**: Time-based expiration with configurable size
4. **Metrics Collection**: Lightweight in-memory metrics with summaries
5. **Dependency Injection**: Constructor injection for all dependencies

## Technical Context
From previous PRs:
- StorageBackend provides the data access layer
- FTS5QueryBuilder handles query construction
- Both are injected into SearchService

From the milestone document:
- PR 4 is medium size, medium risk, high value
- Blocks PR 6 (Application Layer needs SearchService)
- Should enable gradual rollout and testing

## Review Focus Areas
Please review the PR 4 implementation plan focusing on:
1. **Service Design**: Is the SearchService API well-designed and complete?
2. **Feature Flag System**: Is the implementation robust and safe for production?
3. **Caching Strategy**: Will the LRU cache with TTL work well for this use case?
4. **Metrics Design**: Are we collecting the right metrics without too much overhead?
5. **Migration Safety**: Is the gradual rollout plan safe and reversible?
6. **Performance**: Will the service layer add acceptable overhead?
7. **Testing**: Is the test coverage comprehensive?

## Related Documents
- `/home/momer/projects/dcek/code-query-mcp/pr4_implementation_plan.md` - The implementation plan
- `/home/momer/projects/dcek/code-query-mcp/ddd_milestone_breakdown_v3.md` - Overall architecture
- `/home/momer/projects/dcek/code-query-mcp/storage/sqlite_storage.py` - Current search implementation