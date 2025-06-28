# PR 3: Extract Query Builder with Fallback Support

## Overview
This PR extracts query building logic into a dedicated module with support for code-aware query construction and fallback strategies. It addresses the complexity of FTS5 query syntax and provides graceful degradation when strict queries fail.

**Size**: Medium | **Risk**: Low | **Value**: High

## Dependencies
- PR 1 must be completed (tokenizer fixes enable proper query building)
- This PR blocks PR 4 (Search Service needs query builder)

## Objectives
1. Extract all FTS5 query building logic from sqlite_storage.py
2. Implement code-aware query strategies that preserve operators
3. Add fallback mechanisms for when strict queries return no results
4. Support different query building strategies via strategy pattern
5. Provide clear abstraction for future query enhancements

## Implementation Steps

### Step 1: Create Directory Structure
```
search/
├── __init__.py              # Export main classes
├── query_builder.py         # Main FTS5QueryBuilder class
├── query_strategies.py      # Different query building strategies
├── tokenizer_config.py      # Tokenizer-aware query adjustments
└── query_utils.py           # Shared utilities and helpers
```

### Step 2: Define Query Builder Interface
**File**: `search/query_builder.py`
- Main FTS5QueryBuilder class
- Strategy pattern for extensibility
- Primary and fallback query methods
- Clear API for consumers

### Step 3: Implement Query Strategies
**File**: `search/query_strategies.py`
- DefaultQueryStrategy - basic FTS5 queries
- CodeAwareQueryStrategy - preserves code symbols
- FallbackStrategy - looser matching patterns
- Abstract base class for custom strategies

### Step 4: Implement Tokenizer Configuration
**File**: `search/tokenizer_config.py`
- Constants for tokenizer special characters
- Query adjustments based on tokenizer
- Symbol preservation logic

### Step 5: Extract Existing Logic
- Move `_build_fts5_query` from sqlite_storage.py
- Move `_escape_fts5_query` logic
- Consolidate scattered query building code
- Maintain backward compatibility

### Step 6: Add Query Utilities
**File**: `search/query_utils.py`
- Common query transformations
- Operator detection and handling
- Term extraction and analysis

## Detailed Implementation

### search/query_builder.py
```python
from abc import ABC, abstractmethod
from typing import Optional, List
from .query_strategies import QueryStrategy, CodeAwareQueryStrategy, FallbackStrategy

class FTS5QueryBuilder:
    """Builds optimized FTS5 queries with operator preservation and fallback support."""
    
    def __init__(self, primary_strategy: Optional[QueryStrategy] = None,
                 fallback_strategy: Optional[QueryStrategy] = None):
        """
        Initialize query builder with strategies.
        
        Args:
            primary_strategy: Main query building strategy
            fallback_strategy: Strategy to use when primary returns no results
        """
        self.primary_strategy = primary_strategy or CodeAwareQueryStrategy()
        self.fallback_strategy = fallback_strategy or FallbackStrategy()
    
    def build_query(self, user_query: str) -> str:
        """
        Build FTS5 query from user input.
        
        Args:
            user_query: Raw query string from user
            
        Returns:
            FTS5-formatted query string
        """
        if not user_query or not user_query.strip():
            return '""'  # Empty query
            
        return self.primary_strategy.build(user_query)
    
    def build_fallback_query(self, user_query: str) -> str:
        """
        Build a less strict query for fallback searches.
        
        Args:
            user_query: Raw query string from user
            
        Returns:
            FTS5-formatted fallback query
        """
        if not user_query or not user_query.strip():
            return '""'
            
        return self.fallback_strategy.build(user_query)
    
    def get_query_variants(self, user_query: str) -> List[str]:
        """
        Get multiple query variants for progressive searching.
        
        Args:
            user_query: Raw query string from user
            
        Returns:
            List of query variants from most to least specific
        """
        variants = []
        
        # Primary query
        primary = self.build_query(user_query)
        if primary and primary != '""':
            variants.append(primary)
        
        # Fallback query
        fallback = self.build_fallback_query(user_query)
        if fallback and fallback != '""' and fallback != primary:
            variants.append(fallback)
        
        # Additional variants from fallback strategy
        if hasattr(self.fallback_strategy, 'get_additional_variants'):
            additional = self.fallback_strategy.get_additional_variants(user_query)
            for variant in additional:
                if variant not in variants:
                    variants.append(variant)
        
        return variants
```

### search/query_strategies.py
```python
from abc import ABC, abstractmethod
import re
from typing import List, Set
from .tokenizer_config import TOKENIZER_CHARS, CODE_OPERATORS
from .query_utils import extract_terms, escape_special_chars

class QueryStrategy(ABC):
    """Abstract base class for query building strategies."""
    
    @abstractmethod
    def build(self, query: str) -> str:
        """Build FTS5 query from user input."""
        pass

class DefaultQueryStrategy(QueryStrategy):
    """Basic FTS5 query building with minimal processing."""
    
    def build(self, query: str) -> str:
        """Build basic FTS5 query."""
        # Escape special FTS5 characters
        escaped = escape_special_chars(query)
        
        # Simple tokenization and joining
        terms = escaped.split()
        return ' '.join(terms)

class CodeAwareQueryStrategy(QueryStrategy):
    """Query strategy that preserves code-specific patterns and operators."""
    
    def build(self, query: str) -> str:
        """Build query preserving code patterns."""
        # Handle exact phrases first
        if query.startswith('"') and query.endswith('"'):
            return query
        
        # Check for FTS5 operators
        if self._contains_fts5_operators(query):
            # User knows FTS5 syntax, minimal processing
            return self._process_advanced_query(query)
        
        # Process as code query
        return self._process_code_query(query)
    
    def _contains_fts5_operators(self, query: str) -> bool:
        """Check if query contains FTS5 operators."""
        operators = {'AND', 'OR', 'NOT', 'NEAR', '*', '^'}
        tokens = query.split()
        return any(token in operators for token in tokens)
    
    def _process_advanced_query(self, query: str) -> str:
        """Process query that already contains FTS5 operators."""
        # Preserve user's operators but escape special chars in terms
        parts = []
        tokens = query.split()
        
        for token in tokens:
            if token in {'AND', 'OR', 'NOT', 'NEAR'}:
                parts.append(token)
            elif token.startswith('"') and token.endswith('"'):
                parts.append(token)  # Preserve quoted phrases
            else:
                parts.append(escape_special_chars(token))
        
        return ' '.join(parts)
    
    def _process_code_query(self, query: str) -> str:
        """Process as code-aware query."""
        # Check if it's a code pattern (contains special chars)
        if any(char in query for char in TOKENIZER_CHARS):
            # Likely a code identifier, search as phrase
            return f'"{escape_special_chars(query)}"'
        
        # Regular terms, join with implicit AND
        terms = extract_terms(query)
        escaped_terms = [escape_special_chars(term) for term in terms]
        return ' '.join(escaped_terms)

class FallbackStrategy(QueryStrategy):
    """Provides multiple fallback approaches for failed queries."""
    
    def build(self, query: str) -> str:
        """Build primary fallback query - usually phrase search."""
        return self.phrase_search_fallback(query)
    
    def phrase_search_fallback(self, query: str) -> str:
        """Convert to phrase search for exact matching."""
        cleaned = escape_special_chars(query)
        return f'"{cleaned}"'
    
    def prefix_match_fallback(self, query: str) -> str:
        """Add prefix matching to all terms."""
        terms = extract_terms(query)
        prefix_terms = []
        
        for term in terms:
            escaped = escape_special_chars(term)
            # Only add * if term doesn't already have it
            if not escaped.endswith('*'):
                prefix_terms.append(f'{escaped}*')
            else:
                prefix_terms.append(escaped)
        
        return ' '.join(prefix_terms)
    
    def or_search_fallback(self, query: str) -> str:
        """Convert AND search to OR search."""
        terms = extract_terms(query)
        if len(terms) <= 1:
            return escape_special_chars(query)
        
        escaped_terms = [escape_special_chars(term) for term in terms]
        return ' OR '.join(escaped_terms)
    
    def keyword_extraction_fallback(self, query: str) -> str:
        """Extract key terms and search for any."""
        # Remove common words, keep technical terms
        terms = extract_terms(query)
        keywords = self._extract_keywords(terms)
        
        if not keywords:
            return self.or_search_fallback(query)
        
        escaped_keywords = [escape_special_chars(kw) for kw in keywords]
        return ' OR '.join(escaped_keywords)
    
    def _extract_keywords(self, terms: List[str]) -> List[str]:
        """Extract likely important terms."""
        # Common words to filter out
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
            'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is',
            'was', 'are', 'were', 'been', 'be', 'being'
        }
        
        keywords = []
        for term in terms:
            term_lower = term.lower()
            # Keep if not a stop word or contains special chars (likely code)
            if term_lower not in stop_words or any(c in term for c in TOKENIZER_CHARS):
                keywords.append(term)
        
        return keywords
    
    def get_additional_variants(self, query: str) -> List[str]:
        """Get additional query variants for progressive searching."""
        variants = []
        
        # Try prefix matching
        prefix_variant = self.prefix_match_fallback(query)
        if prefix_variant != self.build(query):
            variants.append(prefix_variant)
        
        # Try OR search if multiple terms
        terms = extract_terms(query)
        if len(terms) > 1:
            or_variant = self.or_search_fallback(query)
            variants.append(or_variant)
        
        # Try keyword extraction for long queries
        if len(terms) > 3:
            keyword_variant = self.keyword_extraction_fallback(query)
            if keyword_variant not in variants:
                variants.append(keyword_variant)
        
        return variants
```

### search/tokenizer_config.py
```python
"""Configuration for FTS5 tokenizer and code-aware searching."""

# Characters configured in tokenizer (from PR 1)
TOKENIZER_CHARS = '._$@->:#'

# Common code operators and patterns
CODE_OPERATORS = {
    '->',   # Object member access (C/C++)
    '::',   # Scope resolution (C++)
    '=>',   # Arrow function (JS)
    '.',    # Property access
    '_',    # Snake case
    '$',    # jQuery, PHP variables
    '@',    # Decorators, directives
    '#',    # CSS IDs, preprocessor
}

# Patterns that indicate code search
CODE_PATTERNS = [
    r'^[_$]',                    # Starts with _ or $
    r'[a-z]+_[a-z]+',           # snake_case
    r'[a-z]+[A-Z]',             # camelCase
    r'::\w+',                   # ::method
    r'->\w+',                   # ->property
    r'\w+\$',                   # observable$
    r'#\w+',                    # #identifier
]

def is_code_pattern(term: str) -> bool:
    """Check if a term looks like a code pattern."""
    # Contains tokenizer special chars
    if any(char in term for char in TOKENIZER_CHARS):
        return True
    
    # Matches code patterns
    import re
    for pattern in CODE_PATTERNS:
        if re.search(pattern, term):
            return True
    
    return False
```

### search/query_utils.py
```python
"""Utilities for query processing and manipulation."""

import re
from typing import List, Set

def escape_special_chars(query: str) -> str:
    """Escape special characters for FTS5."""
    # FTS5 special characters that need escaping
    special_chars = '"'
    
    for char in special_chars:
        query = query.replace(char, f'{char}{char}')
    
    return query

def extract_terms(query: str) -> List[str]:
    """Extract individual terms from query."""
    # Handle quoted phrases
    phrases = []
    remaining = query
    
    # Extract quoted phrases first
    quote_pattern = r'"([^"]+)"'
    for match in re.finditer(quote_pattern, query):
        phrases.append(match.group(1))
        remaining = remaining.replace(match.group(0), ' ')
    
    # Split remaining by whitespace
    terms = remaining.split()
    
    # Combine phrases and terms
    all_terms = phrases + [t for t in terms if t]
    
    return all_terms

def detect_operators(query: str) -> Set[str]:
    """Detect FTS5 operators in query."""
    operators = {'AND', 'OR', 'NOT', 'NEAR'}
    tokens = query.split()
    found = set()
    
    for token in tokens:
        if token in operators:
            found.add(token)
    
    return found

def normalize_whitespace(query: str) -> str:
    """Normalize whitespace in query."""
    return ' '.join(query.split())

def is_phrase_query(query: str) -> bool:
    """Check if entire query is a phrase."""
    query = query.strip()
    return query.startswith('"') and query.endswith('"')

def split_camel_case(term: str) -> List[str]:
    """Split camelCase term into words."""
    # Insert space before uppercase letters
    spaced = re.sub(r'(?<!^)(?=[A-Z])', ' ', term)
    return spaced.split()

def split_snake_case(term: str) -> List[str]:
    """Split snake_case term into words."""
    return term.split('_')
```

## Testing Plan

### Unit Tests

#### test_query_builder.py
```python
def test_empty_query():
    """Test handling of empty queries."""
    builder = FTS5QueryBuilder()
    assert builder.build_query("") == '""'
    assert builder.build_query("   ") == '""'

def test_simple_query():
    """Test basic query building."""
    builder = FTS5QueryBuilder()
    assert builder.build_query("login") == "login"
    assert builder.build_query("user auth") == "user auth"

def test_code_pattern_detection():
    """Test code pattern queries become phrases."""
    builder = FTS5QueryBuilder()
    assert builder.build_query("$httpClient") == '"$httpClient"'
    assert builder.build_query("my_function") == '"my_function"'
    assert builder.build_query("obj->method") == '"obj->method"'

def test_fallback_generation():
    """Test fallback query generation."""
    builder = FTS5QueryBuilder()
    primary = builder.build_query("complex query")
    fallback = builder.build_fallback_query("complex query")
    assert primary != fallback
    assert fallback == '"complex query"'

def test_query_variants():
    """Test generation of query variants."""
    builder = FTS5QueryBuilder()
    variants = builder.get_query_variants("user authentication system")
    assert len(variants) >= 2
    assert variants[0] != variants[1]
```

#### test_query_strategies.py
```python
def test_code_aware_strategy():
    """Test code-aware query building."""
    strategy = CodeAwareQueryStrategy()
    
    # Code patterns become phrases
    assert strategy.build("$var") == '"$var"'
    assert strategy.build("my_func") == '"my_func"'
    
    # Regular terms stay separate
    assert strategy.build("login user") == "login user"
    
    # Preserve FTS5 operators
    assert strategy.build("login OR signup") == "login OR signup"

def test_fallback_strategies():
    """Test various fallback approaches."""
    strategy = FallbackStrategy()
    
    # Phrase fallback
    assert strategy.phrase_search_fallback("multi word") == '"multi word"'
    
    # Prefix fallback
    assert strategy.prefix_match_fallback("user log") == "user* log*"
    
    # OR fallback
    assert strategy.or_search_fallback("user login auth") == "user OR login OR auth"
    
    # Keyword extraction
    keywords = strategy.keyword_extraction_fallback("the user authentication system")
    assert "the" not in keywords
    assert "user" in keywords
```

#### test_tokenizer_config.py
```python
def test_code_pattern_detection():
    """Test code pattern detection."""
    from search.tokenizer_config import is_code_pattern
    
    assert is_code_pattern("$var") == True
    assert is_code_pattern("my_function") == True
    assert is_code_pattern("camelCase") == True
    assert is_code_pattern("regular") == False
```

### Integration Tests
```python
def test_query_builder_with_storage():
    """Test query builder integrates with storage."""
    builder = FTS5QueryBuilder()
    # Test that generated queries work with actual FTS5
    
def test_fallback_flow():
    """Test complete fallback flow."""
    # Primary query returns no results
    # Fallback query returns results
    # Verify correct behavior
```

## Migration Strategy

### Phase 1: Extract and Enhance
1. Create new search module with all classes
2. Move existing query building logic
3. Add new features (fallback, strategies)
4. Keep sqlite_storage.py unchanged initially

### Phase 2: Integration
1. Update sqlite_storage.py to use FTS5QueryBuilder
2. Replace inline query building with builder calls
3. Add fallback support to search methods
4. Maintain backward compatibility

### Phase 3: Optimization
1. Profile query performance
2. Tune strategies based on usage patterns
3. Add caching for common queries
4. Document best practices

## Integration with Storage

### Update sqlite_storage.py
```python
from search.query_builder import FTS5QueryBuilder

class SqliteStorage:
    def __init__(self, db_path: str):
        # ... existing init ...
        self.query_builder = FTS5QueryBuilder()
    
    def search_files(self, query: str, dataset: str, limit: int = 10):
        """Search with automatic fallback."""
        # Try primary query
        fts_query = self.query_builder.build_query(query)
        results = self._execute_search(fts_query, dataset, limit)
        
        # If no results, try fallback
        if not results:
            fallback_query = self.query_builder.build_fallback_query(query)
            results = self._execute_search(fallback_query, dataset, limit)
        
        return results
```

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Over-aggressive escaping | Valid queries fail | Comprehensive test suite with edge cases |
| Fallback too broad | Irrelevant results | Multiple fallback levels, user feedback |
| Performance regression | Slower searches | Cache processed queries, profile hot paths |
| Complex queries break | Power users affected | Detect and preserve FTS5 operators |
| Strategy conflicts | Inconsistent results | Clear strategy boundaries and priorities |

## Success Criteria

1. **Query Quality**:
   - Code patterns correctly identified and preserved
   - FTS5 operators work when used explicitly
   - Fallback provides relevant results

2. **Performance**:
   - Query building < 1ms for typical queries
   - No regression in search performance
   - Efficient fallback detection

3. **Maintainability**:
   - Clear separation of concerns
   - Easy to add new strategies
   - Well-documented patterns

4. **User Experience**:
   - Intuitive query behavior
   - Helpful results even for imperfect queries
   - Power users can use advanced features

## Documentation Updates

1. Document query syntax for users
2. Explain fallback behavior
3. Provide examples of supported queries
4. Document strategy pattern for developers

## Review Checklist

- [ ] All query building logic extracted
- [ ] Code patterns properly detected
- [ ] Fallback strategies comprehensive
- [ ] FTS5 operators preserved
- [ ] Performance benchmarked
- [ ] Edge cases tested
- [ ] Integration smooth
- [ ] Documentation complete