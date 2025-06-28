# PR 3 Implementation Plan - Review Context

## Project Context
The Code Query MCP Server now has:
1. Fixed FTS5 tokenizer that preserves code tokens (PR 1 - complete)
2. Storage backend interface with DTOs (PR 2 - complete)

PR 3 extracts query building logic to handle the complexity of FTS5 queries for code search.

## Problem Being Solved
- FTS5 query syntax is complex and error-prone
- Code patterns need special handling (e.g., `$var`, `my_function`)
- When strict queries fail, users get no results
- Query building logic is scattered throughout sqlite_storage.py

## PR 3 Objectives
1. Centralize all query building logic
2. Implement code-aware query strategies
3. Add fallback mechanisms for better UX
4. Use strategy pattern for extensibility
5. Maintain backward compatibility

## Key Design Decisions
1. **Strategy Pattern**: Different strategies for different query types
2. **Progressive Fallback**: Try strict then looser queries
3. **Code Pattern Detection**: Identify when to use phrase queries
4. **Operator Preservation**: Respect explicit FTS5 operators

## Technical Context
From the tokenizer fix (PR 1):
- Tokenizer now preserves: `._$@->:#`
- This enables proper code search
- But queries must be built correctly to leverage this

From the milestone document:
- PR 3 is medium size, low risk, high value
- Blocks PR 4 (Search Service needs query builder)
- Should support multiple fallback strategies

## Review Focus Areas
Please review the PR 3 implementation plan focusing on:
1. **Query Strategy Design**: Are the strategies comprehensive and well-designed?
2. **Fallback Mechanism**: Is the fallback approach effective and performant?
3. **Code Pattern Detection**: Will it correctly identify code vs natural language?
4. **Integration Approach**: Is the migration strategy safe?
5. **Edge Cases**: Are there query patterns we're not handling?
6. **Performance**: Will query building add significant overhead?

## Related Documents
- `/home/momer/projects/dcek/code-query-mcp/pr3_implementation_plan.md` - The implementation plan
- `/home/momer/projects/dcek/code-query-mcp/ddd_milestone_breakdown_v3.md` - Overall architecture
- `/home/momer/projects/dcek/code-query-mcp/storage/sqlite_storage.py` - Current query logic