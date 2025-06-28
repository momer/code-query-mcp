# Code Query MCP - DDD Refactoring Review Context

## Project Overview
The Code Query MCP Server is a Model Context Protocol server that provides intelligent code search capabilities using SQLite FTS5. Currently experiencing search quality issues (e.g., "execution log" returns poor results) due to query sanitization bugs and architectural limitations.

## Current Issues

### Technical Problems
1. **Critical Bug**: Snippet function hardcoded to wrong column (shows filename instead of match)
2. **Query Sanitization**: Strips essential FTS5 operators (*, (), OR, NOT, NEAR)
3. **Architecture**: Monolithic 1000+ line file mixing multiple concerns

### Architectural Concerns
- All logic in single `storage/sqlite_storage.py` file
- Tight coupling between search, storage, dataset management
- Difficult to test, extend, or optimize individual components
- No clear domain boundaries

## Proposed Solution

### Phase 1: Immediate Fixes (PR 1)
- Fix snippet column bug (2 line changes)
- Unify query processing
- Immediate impact on search quality

### Phase 2: Domain-Driven Refactoring

#### Identified Domains:

1. **Search Domain**
   - Query parsing and building
   - Search execution strategies  
   - Result ranking and formatting
   - Search analytics

2. **Storage Domain**
   - Database connection management
   - Schema management
   - Data persistence operations
   - Transaction handling

3. **Dataset Domain**
   - Dataset lifecycle management
   - Dataset metadata operations
   - Dataset synchronization
   - Worktree handling

4. **Documentation Domain**
   - File documentation CRUD
   - Content indexing
   - Documentation updates

5. **Configuration Domain**
   - Project configuration
   - Git hooks management
   - Settings persistence

## Refactoring Strategy

### PR Sequence:
1. **Critical Fixes** (immediate)
2. **Extract Query Builder** (search/query_builder.py)
3. **Extract Search Service** (search/search_service.py)
4. **Enhanced Query Features** (code-aware tokenization)
5. **Storage Backend Interface** (enable future backends)
6. **Dataset Service** (dataset lifecycle management)
7. **Search Analytics** (performance tracking)
8. **Configuration Service** (settings management)

### Key Design Decisions:

1. **Parallel Implementation**: New modules coexist with old code during migration
2. **Interface Preservation**: No breaking changes to MCP tools
3. **Incremental Migration**: Each PR is independently deployable
4. **Clear Boundaries**: Each domain has distinct responsibilities

## Questions for Review

1. **Domain Boundaries**: Are the identified domains appropriate? Should we split/merge any?

2. **Implementation Order**: Does the PR sequence make sense? Should we prioritize differently?

3. **Query Builder Design**: Should we use strategy pattern for different query types?

4. **Storage Abstraction**: Is the backend interface sufficient for future needs (PostgreSQL, Elasticsearch)?

5. **Testing Strategy**: Should we add integration tests between PRs or wait until end?

6. **Risk Assessment**: Any concerns about the migration approach?

## Code Style Considerations

- Following Python type hints throughout
- Using abstract base classes for interfaces
- Dependency injection for testability
- Clear docstrings for domain concepts
- No emojis in code or comments

## Files for Reference

1. `/home/momer/projects/dcek/code-query-mcp/refined_search_improvements_plan.md` - Original improvement plan
2. `/home/momer/projects/dcek/code-query-mcp/ddd_milestone_breakdown.md` - Detailed PR breakdown
3. `/home/momer/projects/dcek/code-query-mcp/storage/sqlite_storage.py` - Current monolithic implementation

## Specific Review Areas

1. **Search Service API**: Does the proposed interface make sense?
2. **Migration Risk**: Any concerns about parallel implementation?
3. **Domain Coupling**: How to handle cross-domain operations?
4. **Performance**: Will the abstraction layers impact search speed?
5. **Future Extensibility**: Are we building the right foundations?