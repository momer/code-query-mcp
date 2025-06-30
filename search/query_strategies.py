"""Query building strategies for different search scenarios."""

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
        # Preserve user's operators but handle code patterns in terms
        parts = []
        tokens = query.split()
        
        for token in tokens:
            if token in {'AND', 'OR', 'NOT', 'NEAR'}:
                parts.append(token)
            elif token.startswith('"') and token.endswith('"'):
                parts.append(token)  # Preserve quoted phrases
            elif any(char in token for char in TOKENIZER_CHARS):
                # Code pattern - quote it
                parts.append(f'"{escape_special_chars(token)}"')
            else:
                parts.append(escape_special_chars(token))
        
        return ' '.join(parts)
    
    def _process_code_query(self, query: str) -> str:
        """Process as code-aware query."""
        # Check if entire query is a code pattern
        if any(char in query for char in TOKENIZER_CHARS):
            # Complex - need to handle mixed terms
            terms = extract_terms(query)
            processed_terms = []
            
            for term in terms:
                # Check each term individually
                if any(char in term for char in TOKENIZER_CHARS):
                    # This term is a code pattern, quote it
                    processed_terms.append(f'"{escape_special_chars(term)}"')
                else:
                    # Regular term
                    processed_terms.append(escape_special_chars(term))
            
            return ' '.join(processed_terms)
        
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