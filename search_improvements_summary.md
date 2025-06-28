# Search Improvements Summary

## Current Issues Identified

1. **Query Sanitization Bug**: Lines 444 and 514 use `re.sub(r'[^\w\s".-]', ' ', query)` which strips out essential FTS5 operators:
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

## Proposed Improvements

1. **Smart Query Processing**: Replace aggressive sanitization with intelligent FTS5 query building
2. **Enhanced Search Features**: Support phrase queries, proximity search, boolean operators
3. **Better Query Expansion**: Handle multi-word queries like "execution log" more intelligently
4. **Improved Ranking**: Better relevance scoring and result ordering

## Implementation Plan

1. Create new `_build_fts5_query()` method for intelligent query processing
2. Update `search_files()` and `search_full_content()` to use improved query building
3. Add fallback strategies for complex queries
4. Maintain backward compatibility
5. Test with "execution log" example

## Goals

- Fix the query sanitization bug that prevents advanced FTS5 features
- Improve search relevance for multi-word queries
- Maintain existing snippet functionality (already good)
- Enable proper FTS5 syntax as documented in tool descriptions