# Code Query MCP Search Implementation Analysis

## Overview
The code-query-mcp project implements a comprehensive search system using SQLite with FTS5 (Full-Text Search) capabilities. The search functionality is designed to handle code documentation and source code content across multiple datasets.

## Architecture

### Core Components
1. **Storage Layer**: `/home/momer/projects/dcek/code-query-mcp/storage/sqlite_storage.py`
2. **Schema Migrations**: `/home/momer/projects/dcek/code-query-mcp/storage/migrations.py`
3. **MCP Tools**: `/home/momer/projects/dcek/code-query-mcp/tools/mcp_tools.py`

### Database Schema

#### Main Tables
- **files**: Primary table storing file documentation
  - `dataset_id`: Dataset identifier
  - `filepath`: Full file path
  - `filename`: File name
  - `overview`: File overview/description
  - `ddd_context`: Domain-driven design context
  - `functions`: JSON of function definitions
  - `exports`: JSON of exported items
  - `imports`: JSON of imported items
  - `types_interfaces_classes`: JSON of type definitions
  - `constants`: JSON of constants
  - `dependencies`: JSON of dependencies
  - `other_notes`: Additional notes
  - `documented_at_commit`: Git commit hash when documented
  - `documented_at`: Timestamp
  - `full_content`: Full source code content (v1.1.0+)

- **files_fts**: FTS5 virtual table for full-text search
  - Indexes all columns from `files` table
  - Uses content='files' and content_rowid='rowid' for external content table
  - Includes triggers for automatic synchronization

- **dataset_metadata**: Dataset management
  - `dataset_id`: Primary key
  - `source_dir`: Source directory
  - `files_count`: Number of files
  - `loaded_at`: Load timestamp
  - `dataset_type`: Type (main, fork, etc.)
  - `parent_dataset_id`: Parent dataset reference
  - `source_branch`: Git branch

#### FTS5 Configuration
```sql
CREATE VIRTUAL TABLE files_fts USING fts5(
    dataset_id UNINDEXED,
    filepath,
    filename,
    overview,
    ddd_context,
    functions,
    exports,
    imports,
    types_interfaces_classes,
    constants,
    dependencies,
    other_notes,
    full_content,
    content='files',
    content_rowid='rowid'
)
```

### Search Functions

#### 1. `search_files(query, dataset_name, limit=10)`
- **Purpose**: Search file metadata (names, overviews, functions, etc.)
- **FTS5 Query**: Uses standard FTS5 MATCH syntax
- **Fallback**: LIKE queries if FTS5 unavailable
- **Returns**: filepath, filename, overview, ddd_context, match_snippet

#### 2. `search_full_content(query, dataset_name, limit=10)`
- **Purpose**: Search actual source code content
- **FTS5 Query**: Uses column-specific search `full_content:query`
- **Fallback**: LIKE queries on full_content column
- **Returns**: filepath, filename, overview, ddd_context, content_snippet, rank

#### 3. `search(query, dataset_name, limit=10)` (Unified Search)
- **Purpose**: Combines metadata and content search
- **Process**:
  1. Performs both metadata and content searches
  2. Deduplicates results by filepath
  3. Merges content snippets into metadata results where applicable
- **Returns**: Structured response with metadata_results, content_results, and search_summary

### Query Processing

#### FTS5 Query Sanitization
```python
# Remove potentially problematic characters and escape quotes
fts_query = re.sub(r'[^\w\s".-]', ' ', query)
fts_query = fts_query.replace('"', '""')  # Escape quotes
fts_query = fts_query.strip()
```

#### Supported FTS5 Syntax
- **Basic**: Multiple words ANDed together (`auth login`)
- **Phrases**: Exact phrases (`"user authentication"`)
- **Prefix**: Prefix matching (`auth*`)
- **Boolean**: OR, NOT operators (`login OR signup`)
- **Column-specific**: Search specific fields (`overview:authentication`)
- **Proximity**: NEAR operator (`NEAR(auth login, 5)`)

### MCP Tool Integration

#### Available Tools
1. **search_files**: Metadata search with discovery-focused results
2. **search_full_content**: Deep content search with code snippets
3. **search**: Unified search combining both approaches

#### Tool Descriptions
- Emphasize code search vs. web search
- Provide usage examples and query syntax
- Guide users on when to use each tool

### Fallback Mechanisms
- **No FTS5**: Falls back to LIKE queries across all searchable columns
- **Column Filtering**: Searches across filepath, filename, overview, ddd_context, functions, exports, imports, types, constants
- **Content Search**: Uses SUBSTR for context-aware snippets

### Performance Features
- **WAL Mode**: Enabled for better concurrency
- **Indexes**: Efficient dataset_id and filepath indexing
- **Triggers**: Automatic FTS synchronization
- **Ranking**: FTS5 BM25 ranking for relevance

### Migration Support
- **Schema Versioning**: Tracked in schema_version table
- **Backward Compatibility**: Handles legacy schemas
- **Column Additions**: Progressive schema enhancement (v1.0.0 → v1.1.0)

## Key Strengths
1. **Comprehensive Coverage**: Searches both metadata and content
2. **Fallback Support**: Works without FTS5 if needed
3. **Query Flexibility**: Supports various FTS5 syntax patterns
4. **Performance**: Optimized with proper indexing and WAL mode
5. **Dataset Isolation**: Multi-dataset support with proper scoping

## Areas for Potential Enhancement
1. **Query Parsing**: Could be more sophisticated for complex queries
2. **Ranking**: Could incorporate custom ranking factors
3. **Snippet Quality**: Content snippets could be enhanced
4. **Caching**: No query result caching currently implemented
5. **Analytics**: No search analytics or query optimization tracking