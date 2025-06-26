# Full-Content Search Implementation Summary

## Overview
Added full-text search capabilities to the code-query MCP by storing complete file contents in the database and providing FTS5 search functionality.

## Changes Made

### 1. Database Schema Updates
- **New Column**: Added `full_content TEXT` column to the `files` table
- **Migration Support**: Added `_migrate_to_v1_1_0()` method in `storage/migrations.py` to handle schema upgrades
- **FTS5 Integration**: Updated FTS5 virtual table and triggers to include the `full_content` column

### 2. Data Import Enhancement  
- **`import_data()` function**: Now reads actual source files and stores their content alongside metadata
- **`insert_file_documentation()` function**: Automatically reads and stores file content when documenting files
- **Error Handling**: Graceful handling of unreadable files with appropriate error messages

### 3. Search Functionality
- **New Function**: `search_full_content()` method for searching within actual source code
- **FTS5 Optimization**: Uses column-specific search (`full_content:query`) for better performance
- **Fallback Support**: LIKE-based search when FTS5 is unavailable
- **Context Snippets**: Returns highlighted snippets showing match context with `[MATCH]` markers

### 4. MCP Interface
- **New Tool**: `search_full_content` tool added to MCP interface
- **Server Handler**: Added handler in `server.py` for the new search functionality
- **Documentation**: Comprehensive tool description with usage examples

## Key Features

### Content Storage
- Reads complete file contents during import/documentation
- Handles encoding issues with `errors='replace'`
- Stores content alongside existing metadata

### Search Capabilities
- Full-text search across actual source code
- FTS5-powered search with ranking
- Snippet extraction with match highlighting
- Fallback LIKE search for compatibility

### Performance Considerations
- FTS5 virtual table for fast full-text search
- Automatic triggers keep FTS index synchronized
- Column-specific search reduces false positives

## Usage Examples

```python
# Search for function definitions
query_server.search_full_content("function calculateTotal", "my_dataset")

# Find constant declarations
query_server.search_full_content("const API_URL", "my_dataset") 

# Search for error handling patterns
query_server.search_full_content("catch (error)", "my_dataset")
```

## Benefits
1. **Deep Code Search**: Find specific implementations, not just metadata
2. **Context Awareness**: See actual code snippets where matches occur
3. **Complementary**: Works alongside existing metadata search
4. **Performance**: FTS5 provides fast, ranked search results
5. **Backwards Compatible**: Existing functionality unchanged

## Implementation Notes
- Database migration handles existing installations seamlessly
- File content reading is robust with proper error handling
- FTS5 triggers automatically maintain search index
- Never returns full file content in search results to avoid overwhelming responses