# PR 1: Critical Bug Fixes + FTS5 Tokenizer Enhancement

## Overview
This PR addresses critical search functionality issues that are currently breaking code search. The primary issue is the default `unicode61` tokenizer splitting programming identifiers inappropriately (e.g., `my_variable` becomes `my` + `variable`).

**Size**: Small | **Risk**: Low | **Value**: CRITICAL

## Objectives
1. Fix FTS5 tokenizer to preserve code-specific tokens
2. Fix snippet column bug in search results
3. Unify query processing across all search methods
4. Add migration to rebuild FTS index with new tokenizer

## Implementation Steps

### Step 1: Create Tokenizer Migration
**File**: `storage/migrations.py`
- Add new migration function `migrate_to_v3_tokenizer`
- Update schema version to 3
- Include FTS rebuild command

### Step 2: Update FTS Table Creation
**File**: `storage/sqlite_storage.py`
- Modify `_create_fts_table()` method (around line 135)
- Change tokenizer configuration to include code-specific characters
- Add tokenchars: `._$@->:#` (includes dot for object access, hash for CSS/comments)

### Step 3: Fix Snippet Column Bug
**File**: `storage/sqlite_storage.py`
- Line 475: Change `snippet(files_fts, 2, ...)` to `snippet(files_fts, 3, ...)` (use full_content column, 0-based index)
- Line 489: Same change for content search snippet
- Note: full_content is the 4th column (index 3) in the FTS table schema

### Step 4: Unify Query Processing
**File**: `storage/sqlite_storage.py`
- Line 553: Replace manual sanitization with `self._build_fts5_query(query)`
- Ensure consistent query handling across all search methods

### Step 5: Update Schema Check
**File**: `storage/sqlite_storage.py`
- Update `_check_schema()` to handle version 3
- Ensure migration runs automatically for existing databases

## Testing Plan

### Manual Testing
1. **Token Preservation Tests**:
   - Search for `$httpClient` - should find variables with $ prefix
   - Search for `my_variable` - should find exact matches, not split
   - Search for `obj->method` - should preserve arrow operator
   - Search for `Class::method` - should preserve scope operator

2. **Snippet Functionality**:
   - Verify "execution log" search returns relevant snippets
   - Check that snippets show surrounding context correctly
   - Ensure HTML escaping works properly

3. **Backward Compatibility**:
   - Existing simple searches still work (e.g., "login", "auth")
   - Performance remains comparable
   - No data loss during migration

### Automated Testing
Create test file: `tests/test_tokenizer_fix.py`
```python
def test_tokenizer_preserves_code_tokens():
    # Test underscore preservation
    # Test dollar sign preservation
    # Test operator preservation
    
def test_snippet_column_fix():
    # Test snippet returns for full_content column (index 3)
    # Test HTML escaping in snippets
    
def test_query_unification():
    # Test search_files uses unified query builder
    # Test edge cases handled consistently

def test_tokenizer_handles_edge_cases():
    # Test token with leading underscore
    index_and_search("_internal_var", expected_count=1)
    
    # Test token with trailing dollar sign (e.g., RxJS observables)
    index_and_search("myObservable$", expected_count=1)
    
    # Test token containing a period
    index_and_search("System.out.println", expected_count=1)

    # Test token containing a hyphen
    index_and_search("my-css-class", expected_count=1)

    # Test search for a term that is a substring of a larger token
    index_and_search("http", "httpClient", expected_count=0) # Should not match 'httpClient'
```

## Migration Safety

### Pre-Migration Checks
1. Backup reminder in migration log
2. Check available disk space (rebuild needs temp space)
3. Log migration start/end times
4. Clean up any leftover temp tables from previous failed migrations

### Rollback Plan
The new migration strategy inherently provides safety:
1. Original FTS table remains untouched until new one is built
2. If migration fails, original table is still functional
3. Temporary table is cleaned up on failure
4. Manual recovery only needed if swap operation fails (very rare)

## Performance Considerations

- FTS rebuild will lock table temporarily
- For large datasets (>100k files), rebuild may take 30-60 seconds
- Consider adding progress logging for rebuild operation

## Code Changes Summary

### storage/migrations.py
```python
def migrate_to_v3_tokenizer(db):
    """Add code-aware tokenizer configuration using a safe migration pattern."""
    logger.info("Migrating to schema version 3: Code-aware tokenizer")
    
    temp_table_name = "files_fts_temp_v3"

    try:
        logger.info(f"Creating new FTS table '{temp_table_name}' with updated tokenizer.")
        # Step 1: Create the new table with a temporary name. Clean up if it exists from a prior failed run.
        db.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        db.execute(f"""
            CREATE VIRTUAL TABLE {temp_table_name} USING fts5(
                filepath, filename, overview, full_content,
                functions, exports, imports, types_interfaces_classes,
                constants, dependencies, other_notes, ddd_context,
                content=files,
                tokenize = 'unicode61 tokenchars ''._$@->:#'''
            )
        """)

        logger.info(f"Rebuilding index for '{temp_table_name}'. This may take some time...")
        # Step 2: Populate the new table. This is the long-running, fallible step.
        db.execute(f"INSERT INTO {temp_table_name}({temp_table_name}) VALUES('rebuild')")
        
        # Step 3: Atomically (or as close as possible) swap the tables.
        # The original table is only dropped AFTER the new one is successfully built.
        logger.info("Swapping old FTS table with the new one.")
        db.execute("DROP TABLE files_fts")
        db.execute(f"ALTER TABLE {temp_table_name} RENAME TO files_fts")

        # Step 4: Finalize the migration
        db.execute("UPDATE schema_version SET version = 3")
        db.commit()
        logger.info("Schema migration to version 3 complete.")

    except Exception as e:
        logger.error(f"Migration to v3 failed: {e}. The original FTS table remains intact.")
        # Attempt to clean up the temporary table
        db.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        # Re-raise the exception to halt the application startup and signal failure
        raise
```

### storage/sqlite_storage.py changes
1. Update `_create_fts_table()` tokenizer config to use `._$@->:#`
2. Fix snippet column indices (2 → 3 for full_content column)
3. Replace manual query sanitization with unified builder
4. Update version check in `_check_schema()`

## Success Criteria

1. **Immediate Impact**:
   - Code-specific searches return accurate results
   - No more false negatives for identifier searches
   - Snippet display works correctly

2. **Quality Metrics**:
   - Search for `$httpClient` returns files containing that exact token
   - Search for `my_function_name` doesn't split on underscores
   - Performance remains within 10% of current baseline

3. **User Experience**:
   - Developers can search for code as they write it
   - No need to guess how tokens might be split
   - Intuitive search behavior for programming constructs

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| FTS rebuild fails | Search unavailable | Safe migration pattern - original table untouched until new one complete |
| Performance regression | Slow searches | Benchmark before/after, add indexes if needed |
| Tokenizer too permissive | False positives | Test common cases, adjust tokenchars if needed |
| Migration interruption | Corrupted index or incomplete migration | Use "create, populate, swap" pattern. Original table safe until swap |
| Disk space issues | Migration fails | Check available space before starting, clean up temp tables |

## Documentation Updates

1. Update README with new search capabilities
2. Add examples of code-specific searches
3. Document tokenizer configuration for future reference

## Review Checklist

- [ ] Tokenizer configuration correct
- [ ] Snippet bug fixed in both search methods  
- [ ] Query processing unified
- [ ] Migration handles all edge cases
- [ ] Tests cover new functionality
- [ ] Performance impact measured
- [ ] Documentation updated