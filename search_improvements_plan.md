# Search Improvements Plan for code-query-mcp

## Project Context
This is a code-query MCP server that provides intelligent code search functionality using SQLite FTS5. The user has identified that search queries like "execution log" are not returning good results, even though relevant documentation exists.

## Problem Analysis

### Current Issues Identified
1. **Query sanitization is too aggressive** - Lines 444 and 514 use `re.sub(r'[^\w\s".-]', ' ', query)` which strips out essential FTS5 operators:
   - `*` (prefix matching)
   - `()` (grouping)
   - `OR` and `NOT` (boolean operators) 
   - `NEAR` (proximity)
   - `+` and `-` (required/excluded terms)

2. **Limited Search Capabilities**: 
   - No support for phrase queries with quotes
   - No proximity search (NEAR operator)
   - No advanced boolean logic
   - Poor handling of compound queries like "execution log"

3. **Snippet Implementation**: 
   - Already uses snippet() function correctly
   - Uses 64 tokens for metadata search (line 450)
   - Uses 128 tokens for content search (line 520)
   - Good highlighting with [MATCH]/[/MATCH] tags

## Detailed Code Review Findings

### 🔴 CRITICAL Issues

**[CRITICAL] search_files() returns misleading snippets (lines 475, 489)**
- The `snippet()` function is hardcoded to use column index `2` (filename)
- Even if a match is found in `overview` or `ddd_context`, snippet shows from filename
- This makes valid search results appear incorrect/empty
- **Fix**: Change column index from `2` to `-1` to show snippets from ANY matching column

**[CRITICAL] Aggressive sanitization breaks full-content search (line 553)**
- `search_full_content()` uses `re.sub` to strip characters from query
- Breaks valid FTS5 syntax like `NEAR()` or prefix searches with `*`
- Should use the more sophisticated `_build_fts5_query` method
- **Fix**: Replace manual sanitization with call to `self._build_fts5_query(query)`

### 🟠 HIGH Priority Issues

**[HIGH] Single-word queries strip important code characters (line 436)**
- `_build_fts5_query` strips non-alphanumeric characters from single-word queries
- For code search, characters like `_`, `$`, `@`, `->` are significant
- Removing them leads to incorrect searches (e.g., `$http` becomes `http`)
- **Fix**: Preserve special characters and add proper escaping for FTS5 keywords

**[HIGH] Unreliable fallback query logic (line 485)**
- If complex query fails, fallback re-uses original user query
- Likely to fail again for same syntax reason
- **Fix**: Use phrase search as fallback instead

### 🟡 MEDIUM Priority Issues

**[MEDIUM] Inconsistent query processing**
- `search_files()` uses new `_build_fts5_query()` method
- `search_full_content()` still uses old aggressive sanitization
- Should use consistent approach across all search functions

**[MEDIUM] Local import placement (line 551)**
- `import re` inside function instead of at top of file
- Should follow Python conventions

## Implementation Plan

### Phase 1: Fix Critical Snippet Issues
```python
# In search_files() - change snippet column index
snippet(files_fts, -1, '[MATCH]', '[/MATCH]', '...', 64) as match_snippet
# Instead of hardcoded column 2
```

### Phase 2: Unify Query Processing
```python
# In search_full_content() - replace sanitization
fts_query = self._build_fts5_query(query)
# Instead of manual re.sub() sanitization
```

### Phase 3: Improve Query Building
```python
# Enhanced _build_fts5_query for single words
if len(words) == 1:
    word = words[0].replace('"', '""')
    if word.upper() in ('AND', 'OR', 'NOT'):
        return f'"{word}"'
    if not word.endswith('*'):
        word += '*'
    return word
```

### Phase 4: Better Fallback Logic
```python
# Improved fallback in search_files()
except Exception as e:
    logging.warning(f"FTS5 query failed, falling back to phrase search: {e}")
    simple_query = f'"{query.replace('"', '""')}"'
    # Use phrase search instead of re-trying original query
```

## Expected Improvements

### For "execution log" queries:
- **Before**: Empty/irrelevant snippets from filename field
- **After**: Relevant snippets from overview/content where matches actually occur

### For advanced queries:
- **Before**: `auth* OR login` → stripped to `auth OR login` (breaks syntax)
- **After**: `auth* OR login` → works as intended with prefix and boolean operators

### For code search:
- **Before**: `$httpClient` → becomes `httpClient` (loses meaning)
- **After**: `$httpClient*` → finds exact matches and similar patterns

## Architecture Strengths to Preserve

1. **Excellent FTS5 Foundation** - FTS5 with triggers for synchronization is robust
2. **Smart Multi-Word Strategy** - Combining phrase + proximity + AND searches
3. **Clear Separation** - Distinct metadata vs content search functions
4. **Solid Database Management** - Good connection handling and migrations

## Files to Modify
- `/storage/sqlite_storage.py` - Main search implementation
  - `_build_fts5_query()` method improvements
  - `search_files()` snippet and fallback fixes
  - `search_full_content()` query processing unification

## Testing Strategy
1. Test "execution log" query before and after changes
2. Verify advanced FTS5 syntax works (NEAR, OR, *, quotes)
3. Test single-word queries with special characters
4. Ensure fallback logic works for invalid queries
5. Validate snippet highlighting shows relevant context

This plan addresses the root causes while maintaining the existing solid FTS5 foundation and improving the snippet functionality to show the correct context.