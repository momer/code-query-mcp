# Refined Search Improvement Plan

## Critical Analysis & Strategic Approach

After deep technical analysis and research into FTS5 tokenizers, here's the refined plan that balances immediate impact with long-term architectural soundness:

### Phase 1: Critical Bug Fixes (Immediate Impact)
**Target: Fix "execution log" search within hours**

1. **Fix snippet column bug** - Change `snippet(files_fts, 2, ...)` to `snippet(files_fts, -1, ...)` in both `search_files()` locations
   - **Impact**: Immediately shows relevant snippets instead of empty filename matches
   - **Risk**: None - this is a clear bug fix

2. **Unify query processing** - Replace manual `re.sub()` sanitization in `search_full_content()` with `self._build_fts5_query(query)`
   - **Impact**: Consistent query handling across all search functions
   - **Risk**: Low - reuses existing tested logic

### Phase 2: Enhanced Query Building (Medium Priority)
**Target: Enable advanced FTS5 syntax properly**

3. **Improve single-word handling** - Preserve special characters important for code (`_`, `$`, `@`)
   ```python
   if len(words) == 1:
       word = words[0].replace('"', '""')
       if word.upper() in ('AND', 'OR', 'NOT'):
           return f'"{word}"'
       return word  # Preserve special chars
   ```

4. **Better fallback strategy** - Use phrase search instead of retrying failed query
   ```python
   except Exception as e:
       simple_query = f'"{query.replace('"', '""')}"'
   ```

### Phase 3: Strategic Architecture Decision (Future)
**Target: Fundamental tokenizer improvement**

Based on research, the current `unicode61` tokenizer **is breaking code search**:
- `my_variable` → splits into `my` + `variable` 
- `obj->method` → splits into `obj` + `method`
- `$httpClient` → becomes `httpClient`

**Two architectural paths forward:**

**Option A: Built-in Tokenizer Enhancement**
- Use `unicode61 tokenchars '_$@->'` to preserve code symbols
- **Pros**: Simple configuration change, no migration needed
- **Cons**: Limited flexibility, may not handle all code patterns

**Option B: Custom Python Tokenizer** 
- Use `sqlitefts` package for code-aware tokenization
- **Pros**: Full control, optimized for code search
- **Cons**: Requires data migration, additional dependency

**Recommendation**: Start with Option A for immediate improvement, plan Option B for v2.0

### Phase 4: Architectural Improvements
**Target: Long-term maintainability**

5. **Consolidate search functions** - Create shared `_execute_search()` method to eliminate duplication
6. **Enhanced logging** - Track query failures and performance metrics
7. **Robust testing** - Test edge cases like nested operators, special characters

## Technical Deep Dive

### Original Issues Identified

1. **Query sanitization is too aggressive** - Lines 444 and 514 use `re.sub(r'[^\w\s".-]', ' ', query)` which strips out essential FTS5 operators:
   - `*` (prefix matching)
   - `()` (grouping)
   - `OR` and `NOT` (boolean operators) 
   - `NEAR` (proximity)
   - `+` and `-` (required/excluded terms)

2. **Snippet function hardcoded to wrong column** - Shows snippets from filename (column 2) instead of matching column
3. **Inconsistent query processing** between search functions
4. **Poor handling of compound queries** like "execution log"

### Code Review Findings Summary

**🔴 CRITICAL Issues:**
- `search_files()` returns misleading snippets (lines 475, 489)
- Aggressive sanitization breaks full-content search (line 553)

**🟠 HIGH Priority Issues:**
- Single-word queries strip important code characters (line 436)
- Unreliable fallback query logic (line 485)

**🟡 MEDIUM Priority Issues:**
- Inconsistent query processing between functions
- Local import placement issues

### FTS5 Tokenizer Research Findings

**Current Problem:**
The default `unicode61` tokenizer treats underscores, dollar signs, and other code symbols as separators, fundamentally breaking code search.

**Built-in Solutions:**
- `unicode61 tokenchars '_$@->'` - Add code symbols as token characters
- `trigram` tokenizer - Character-level matching for substring search
- `ascii` tokenizer - Treats non-ASCII as token characters

**Custom Solutions:**
- Python `sqlitefts` package allows custom tokenizers
- Requires C-level implementation for maximum performance
- Examples available for code-specific tokenization

## Implementation Strategy

### Immediate (This Sprint)
- Execute Phase 1 fixes 
- Test with "execution log" to validate improvements
- **Expected Result**: 80% improvement in search relevance

### Next Sprint  
- Implement Phase 2 enhancements
- Add tokenizer configuration for code symbols
- **Expected Result**: Support for advanced FTS5 syntax

### Future Roadmap
- Research custom tokenizer implementation
- Plan data migration strategy for tokenizer change
- **Expected Result**: Best-in-class code search

## Risk Assessment

**Low Risk (Phase 1)**
- Snippet fix: Simple column index change
- Query unification: Reuses existing logic

**Medium Risk (Phase 2)**  
- Query building changes may introduce edge cases
- Mitigation: Comprehensive testing, fallback logic

**High Risk (Future)**
- Custom tokenizer requires data migration
- Mitigation: Thorough testing, gradual rollout

## Testing Strategy

### Core Test Cases
1. **"execution log" query** - Primary use case validation
2. **Advanced FTS5 syntax** - `auth* OR login`, `NEAR("user" "session", 5)`
3. **Code searches** - `$httpClient`, `my_variable`, `obj->method`
4. **Edge cases** - Empty queries, special characters, nested operators

### Specific Edge Cases to Test
- **Operator Case**: `auth* or login` (lowercase `or`)
- **Keywords as Terms**: `search for "NEAR" and "OR"`
- **Mismatched Parentheses**: `(auth OR login`
- **Complex Nesting**: `(user AND (token OR session*))`
- **Purely Special Characters**: `*` or `""` or `()`
- **Code-like Strings**: `search for "$user->getId()"`

## Success Metrics

1. **"execution log" query returns relevant results with proper snippets**
2. **Advanced FTS5 syntax works**: `auth* OR login`, `NEAR("user" "session", 5)`
3. **Code searches preserve meaning**: `$httpClient` finds actual matches
4. **No regression in search performance or stability**
5. **Query failure rate < 5%** with proper fallback handling

## Files to Modify

### Primary Implementation
- `/storage/sqlite_storage.py` - Main search implementation
  - `search_files()` - Fix snippet column, improve fallback
  - `search_full_content()` - Unify query processing
  - `_build_fts5_query()` - Enhanced single-word handling

### Future Enhancements
- Database schema migration for tokenizer changes
- Additional test files for comprehensive validation
- Configuration updates for tokenizer settings

## Architecture Strengths to Preserve

1. **Excellent FTS5 Foundation** - FTS5 with triggers for synchronization is robust
2. **Smart Multi-Word Strategy** - Combining phrase + proximity + AND searches
3. **Clear Separation** - Distinct metadata vs content search functions
4. **Solid Database Management** - Good connection handling and migrations

This plan provides immediate wins while establishing foundation for future enhancements. The snippet fix alone will dramatically improve perceived search quality.

## Next Steps

1. **Implement Phase 1 fixes immediately**
2. **Test thoroughly with "execution log" example**
3. **Gather user feedback on search improvements**
4. **Plan Phase 2 implementation based on results**
5. **Research tokenizer migration strategy for Phase 3**