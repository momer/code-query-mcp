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
    
    def get_additional_variants(self, query: str) -> List[str]:
        """Get additional query variants. Base implementation returns none."""
        return []

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
        import re
        # This regex finds:
        # 1. Quoted phrases
        # 2. FTS5 operators (AND, OR, NOT)
        # 3. NEAR() function calls
        # 4. Words (including those with * and code patterns)
        # Match sequences that include word chars and code special chars
        # Use a more specific pattern for tokens
        # Match: quoted phrases | operators | NEAR function | regular words/code patterns
        token_pattern = re.compile(
            r'"[^"]+"|'                           # Quoted phrases
            r'(?<![\w$@._:#])(?:AND|OR|NOT)(?![\w$@._:#])|'  # Operators with custom boundaries
            r'NEAR\([^)]+\)|'                   # NEAR function
            r'[$@_]?\w[\w$@._:#]*(?:->)?[\w$@._:#]*\*?',  # Words and code patterns
            re.IGNORECASE
        )
        
        parts = []
        last_end = 0
        for match in token_pattern.finditer(query):
            # Add any non-matching text (like spaces)
            parts.append(query[last_end:match.start()])
            
            token = match.group(0)
            # Check if the token is a code pattern that isn't already quoted or an operator
            if (not token.startswith('"') and 
                not token.upper() in {'AND', 'OR', 'NOT'} and 
                not token.upper().startswith('NEAR') and
                any(char in token for char in TOKENIZER_CHARS)):
                parts.append(f'"{escape_special_chars(token)}"')
            else:
                parts.append(token)
            last_end = match.end()
        
        # Add any trailing text
        parts.append(query[last_end:])
        
        return ''.join(parts).strip()
    
    def _process_code_query(self, query: str) -> str:
        """Process as code-aware query."""
        terms = extract_terms(query)
        processed_terms = []
        
        for term in terms:
            # Check if the term is a code pattern or a multi-word phrase
            is_code = any(char in term for char in TOKENIZER_CHARS)
            is_phrase = ' ' in term
            
            if is_code or is_phrase:
                # This term is a code pattern or an extracted phrase, quote it
                processed_terms.append(f'"{escape_special_chars(term)}"')
            else:
                # Regular term
                processed_terms.append(escape_special_chars(term))
        
        return ' '.join(processed_terms)

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