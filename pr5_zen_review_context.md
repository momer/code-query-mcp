# PR 5 Implementation Plan - Review Context

## Project Context
The Code Query MCP Server now has:
1. Fixed FTS5 tokenizer (PR 1 - complete)
2. Storage backend interface with DTOs (PR 2 - complete)
3. Query builder with fallback support (PR 3 - complete)
4. Search service with dependency injection (PR 4 - complete)

PR 5 extracts dataset management into a dedicated service with proper lifecycle management, addressing the scattered dataset logic throughout sqlite_storage.py.

## Problem Being Solved
- Dataset operations scattered across 1000+ line sqlite_storage.py
- No clear dataset lifecycle management
- Complex worktree handling mixed with storage logic
- Limited validation and error handling
- No proper dataset synchronization abstraction
- Difficult to track dataset relationships and dependencies

## PR 5 Objectives
1. Extract all dataset operations into DatasetService
2. Implement full lifecycle management (create, fork, sync, delete)
3. Add robust worktree support with automatic detection
4. Provide comprehensive validation
5. Enable efficient dataset synchronization
6. Support dataset statistics and comparison

## Key Design Decisions
1. **Domain Models**: Rich dataset models with types, relationships, and metadata
2. **Lifecycle Management**: Clear create → fork → sync → delete flow
3. **Worktree Integration**: Automatic detection and dataset naming
4. **Validation Layer**: Comprehensive input validation with clear errors
5. **Sync Strategy**: Git-based change detection for efficient transfers
6. **Batch Operations**: Optimize for large dataset copies

## Technical Context
From previous PRs:
- StorageBackend provides the persistence layer
- DTOs ensure type safety across boundaries
- Services use dependency injection throughout

From the milestone document:
- PR 5 is medium size, low risk, medium value
- Blocks PR 6 (Application Layer needs DatasetService)
- Blocks PR 8 (Configuration needs dataset operations)
- Should handle worktree lifecycles cleanly

## Review Focus Areas
Please review the PR 5 implementation plan focusing on:
1. **Service Design**: Is the DatasetService API complete and well-designed?
2. **Lifecycle Management**: Are create, fork, sync, and delete operations robust?
3. **Worktree Handling**: Will the worktree detection and management work reliably?
4. **Sync Implementation**: Is the synchronization logic sound and efficient?
5. **Validation**: Are the validation rules appropriate and comprehensive?
6. **Error Handling**: Are errors properly propagated with good messages?
7. **Performance**: Will batch operations and sync scale well?
8. **Testing**: Is the test coverage adequate for this critical component?

## Critical Considerations
1. **Data Integrity**: Deleting datasets must not leave orphaned data
2. **Sync Reliability**: Must handle conflicts and partial failures gracefully
3. **Worktree Edge Cases**: Various Git configurations and states
4. **Performance at Scale**: Datasets with thousands of files
5. **Backward Compatibility**: Existing dataset operations must continue working

## Related Documents
- `/home/momer/projects/dcek/code-query-mcp/pr5_implementation_plan.md` - The implementation plan
- `/home/momer/projects/dcek/code-query-mcp/ddd_milestone_breakdown_v3.md` - Overall architecture
- `/home/momer/projects/dcek/code-query-mcp/storage/sqlite_storage.py` - Current dataset implementation
- Previous PR implementation plans for context