"""FTS5 query sanitizer that preserves legitimate syntax while preventing injection attacks."""

import re
from typing import List, Tuple, Set, Optional
from dataclasses import dataclass


@dataclass
class SanitizationConfig:
    """Configuration for query sanitization behavior."""
    allow_wildcards: bool = True
    allow_column_filters: bool = False  # Disabled by default for security
    allow_initial_token_match: bool = True
    max_wildcards: int = 5
    max_phrase_length: int = 100


class FTS5QuerySanitizer:
    """
    Sanitizes FTS5 queries to prevent injection while preserving functionality.
    
    This sanitizer takes a balanced approach:
    - Preserves legitimate FTS5 operators and syntax
    - Prevents injection of malicious column filters
    - Validates query complexity to prevent DoS
    - Maintains search functionality for code patterns
    """
    
    # FTS5 operators that should be preserved when standalone
    FTS5_OPERATORS = {'AND', 'OR', 'NOT'}
    
    # Pattern to match NEAR operator with proper syntax
    # Captures: NEAR(terms) or NEAR(terms, distance)
    NEAR_PATTERN = re.compile(
        r'NEAR\s*\(\s*([^,)]+?)(?:\s*,\s*(\d+))?\s*\)',
        re.IGNORECASE
    )
    
    # Pattern to match quoted phrases (handling escaped quotes)
    QUOTED_PHRASE_PATTERN = re.compile(r'"((?:[^"]|"")*)"')
    
    # Pattern to detect column filters (security risk)
    # Matches: word: or -word: or {word word}: but NOT :: (namespace)
    COLUMN_FILTER_PATTERN = re.compile(
        r'(?:^|\s)(\w+(?<!:):(?!:)|-\w+:|{[^}]+}:)',
        re.IGNORECASE
    )
    
    # Pattern to detect initial token match
    # Captures the ^ and the term, but not the preceding space
    INITIAL_TOKEN_PATTERN = re.compile(r'\^(\S+)')
    
    def __init__(self, config: Optional[SanitizationConfig] = None):
        """Initialize sanitizer with configuration."""
        self.config = config or SanitizationConfig()
    
    def sanitize(self, query: str, config: Optional[SanitizationConfig] = None) -> str:
        """
        Sanitize FTS5 query while preserving legitimate functionality.
        
        Args:
            query: Raw user query
            config: Optional configuration to override instance defaults
            
        Returns:
            Sanitized query safe for FTS5
            
        Raises:
            ValueError: If query contains forbidden syntax or is too complex
        """
        if not query or not query.strip():
            return '""'
        
        # Use provided config or fall back to instance config
        config = config or self.config
        
        # Check for column filters if not allowed
        if not config.allow_column_filters:
            if self.COLUMN_FILTER_PATTERN.search(query):
                # Remove column filters rather than rejecting query
                query = self.COLUMN_FILTER_PATTERN.sub(' ', query)
        
        # Extract and validate components
        components = self._extract_query_components(query, config)
        
        # Validate complexity with config
        self._validate_complexity(components, config)
        
        # Reconstruct sanitized query with config
        return self._reconstruct_query(components, config)
    
    def _extract_query_components(self, query: str, config: SanitizationConfig) -> dict:
        """Extract query components for processing."""
        components = {
            'phrases': [],
            'near_clauses': [],
            'wildcards': [],
            'operators': [],
            'regular_terms': [],
            'initial_matches': [],
            'column_filters': [],
            'ordered_components': []  # Track order for reconstruction
        }
        
        remaining = query
        
        # Extract quoted phrases first
        phrase_placeholders = {}
        offset = 0
        
        for i, match in enumerate(self.QUOTED_PHRASE_PATTERN.finditer(query)):
            phrase_content = match.group(1)
            # Validate phrase length
            if len(phrase_content) > config.max_phrase_length:
                phrase_content = phrase_content[:config.max_phrase_length]
            
            # Store sanitized phrase - don't double quotes that are already doubled
            safe_phrase = phrase_content  # Already has proper quote escaping
            components['phrases'].append(f'"{safe_phrase}"')
            
            # Create placeholder
            placeholder = f"__PHRASE_{i}__"
            
            # Calculate adjusted positions
            start = match.start() - offset
            end = match.end() - offset
            
            # Replace in remaining string
            remaining = remaining[:start] + placeholder + remaining[end:]
            
            # Update offset for next iteration
            offset += (end - start) - len(placeholder)
            
            phrase_placeholders[placeholder] = (match.start(), match.end())
        
        # Extract NEAR clauses
        near_placeholders = {}
        near_offset = 0
        
        for i, match in enumerate(self.NEAR_PATTERN.finditer(remaining)):
            terms = match.group(1)
            distance = match.group(2) or "10"  # Default distance
            
            # Terms are now properly parsed by the regex
            
            # Sanitize terms inside NEAR
            safe_terms = self._sanitize_near_terms(terms)
            components['near_clauses'].append(f"NEAR({safe_terms}, {distance})")
            
            # Create placeholder
            placeholder = f"__NEAR_{i}__"
            
            # Calculate adjusted positions
            start = match.start() - near_offset
            end = match.end() - near_offset
            
            # Replace in remaining string
            remaining = remaining[:start] + placeholder + remaining[end:]
            
            # Update offset
            near_offset += (end - start) - len(placeholder)
            
            near_placeholders[placeholder] = (match.start(), match.end())
        
        # Extract column filters if allowed
        column_placeholders = {}
        if self.config.allow_column_filters:
            # Handle column filters before other processing
            parts = remaining.split()
            new_parts = []
            
            for part in parts:
                if ':' in part and not part.startswith('__'):
                    # This might be a column filter
                    if self.COLUMN_FILTER_PATTERN.match(' ' + part):
                        components['column_filters'].append(part)
                        placeholder = f"__COLUMN_{len(components['column_filters'])-1}__"
                        column_placeholders[placeholder] = part
                        new_parts.append(placeholder)
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            
            remaining = ' '.join(new_parts)
        
        # Extract initial token matches if allowed
        initial_placeholders = {}
        initial_offset = 0
        
        if self.config.allow_initial_token_match:
            for i, match in enumerate(self.INITIAL_TOKEN_PATTERN.finditer(remaining)):
                term = match.group(1)
                # Remove wildcards from initial matches (not supported by FTS5)
                safe_term = term.rstrip('*')
                components['initial_matches'].append(f"^{safe_term}")
                
                placeholder = f"__INITIAL_{i}__"
                
                # Calculate adjusted positions
                start = match.start() - initial_offset
                end = match.end() - initial_offset
                
                # Replace in remaining string
                remaining = remaining[:start] + placeholder + remaining[end:]
                
                # Update offset
                initial_offset += (end - start) - len(placeholder)
                
                initial_placeholders[placeholder] = match.start()
        
        # Process remaining tokens while preserving order
        # First, we need to handle code patterns that include parentheses
        import re
        # This pattern matches:
        # 1. Code patterns with -> or :: that might include ()
        # 2. Standalone parentheses
        # 3. Other non-whitespace sequences
        token_pattern = re.compile(r'[$@_]?\w+(?:->|::)\w+\(\)|[()]|[^\s()]+')
        
        token_positions = []
        for match in token_pattern.finditer(remaining):
            token = match.group()
            pos = match.start()
            token_positions.append((token, pos))
        
        # Process each token
        for i, (token, pos) in enumerate(token_positions):
            # Skip placeholders
            if (token.startswith("__PHRASE_") or 
                token.startswith("__NEAR_") or
                token.startswith("__INITIAL_") or
                token.startswith("__COLUMN_")):
                components['ordered_components'].append((token, pos))
                continue
            
            # Check if it's an operator
            if token.upper() in self.FTS5_OPERATORS:
                components['operators'].append((token.upper(), pos))
                components['ordered_components'].append((token.upper(), pos))
                continue
            
            # Handle parentheses
            if token in ['(', ')']:
                components['ordered_components'].append((token, pos))
                continue
            
            # Check for wildcards
            if config.allow_wildcards and '*' in token:
                # Validate wildcard usage (must be at end of term)
                if token.endswith('*') and token.count('*') == 1 and len(token) > 1:
                    components['wildcards'].append(token)
                    components['ordered_components'].append((token, pos))
                else:
                    # Invalid wildcard usage, treat as regular term
                    clean = token.replace('*', '')
                    components['regular_terms'].append(clean)
                    components['ordered_components'].append((clean, pos))
            else:
                # Regular term - keep it as is, will quote if needed later
                clean_term = token.strip()
                if clean_term:
                    components['regular_terms'].append(clean_term)
                    components['ordered_components'].append((clean_term, pos))
        
        # Sort ordered components by position
        components['ordered_components'].sort(key=lambda x: x[1])
        
        return components
    
    def _sanitize_near_terms(self, terms: str) -> str:
        """Sanitize terms within NEAR clause."""
        # Split terms and quote each one to prevent injection
        term_list = terms.split()
        safe_terms = []
        
        for term in term_list:
            # Remove any special characters that could break NEAR syntax
            clean_term = term.strip('"*^,')  # Also strip commas
            if clean_term and not clean_term.isdigit():  # Don't quote numbers (distances)
                # Escape internal quotes before wrapping the term in quotes
                escaped_term = clean_term.replace('"', '""')
                safe_terms.append(f'"{escaped_term}"')
        
        return ' '.join(safe_terms)
    
    def _validate_complexity(self, components: dict, config: SanitizationConfig) -> None:
        """Validate query complexity to prevent DoS."""
        wildcard_count = len(components['wildcards'])
        
        if wildcard_count > config.max_wildcards:
            raise ValueError(
                f"Query contains too many wildcards ({wildcard_count} > "
                f"{config.max_wildcards}). Please be more specific."
            )
        
        # Check total term count
        total_terms = (
            len(components['phrases']) +
            len(components['near_clauses']) +
            len(components['wildcards']) +
            len(components['regular_terms']) +
            len(components['initial_matches'])
        )
        
        if total_terms > 50:  # Reasonable limit
            raise ValueError(
                "Query is too complex. Please simplify your search."
            )
    
    def _reconstruct_query(self, components: dict, config: SanitizationConfig) -> str:
        """Reconstruct sanitized query from components."""
        if not components['ordered_components'] and not components['phrases'] and not components['near_clauses']:
            return '""'
        
        # Create lookup maps for replacements
        phrase_map = {f"__PHRASE_{i}__": phrase for i, phrase in enumerate(components['phrases'])}
        near_map = {f"__NEAR_{i}__": near for i, near in enumerate(components['near_clauses'])}
        initial_map = {f"__INITIAL_{i}__": init for i, init in enumerate(components['initial_matches'])}
        column_map = {f"__COLUMN_{i}__": col for i, col in enumerate(components['column_filters'])}
        
        # Build result maintaining order
        result_parts = []
        
        for component, _ in components['ordered_components']:
            if component in phrase_map:
                result_parts.append(phrase_map[component])
            elif component in near_map:
                result_parts.append(near_map[component])
            elif component in initial_map:
                result_parts.append(initial_map[component])
            elif component in column_map:
                result_parts.append(column_map[component])
            elif component in self.FTS5_OPERATORS:
                # Operators pass through as-is
                result_parts.append(component)
            elif component in ['(', ')']:
                # Parentheses pass through
                result_parts.append(component)
            elif component.endswith('*') and component in components['wildcards']:
                # Valid wildcard
                result_parts.append(component)
            else:
                # Regular term - quote if it contains special characters
                needs_quoting = any(c in component for c in ['$', '_', '-', '>', ':', '.', '@', '+', '#', ';', '*', '(', ')', '[', ']', '{', '}', '"'])
                
                # Also quote if term could be confused with operator
                if component.upper() in self.FTS5_OPERATORS:
                    needs_quoting = True
                
                if needs_quoting:
                    # Escape any quotes in the term
                    escaped = component.replace('"', '""')
                    result_parts.append(f'"{escaped}"')
                else:
                    result_parts.append(component)
        
        return ' '.join(result_parts)
    
    def is_query_safe(self, query: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a query is safe without modifying it.
        
        Args:
            query: Query to check
            
        Returns:
            Tuple of (is_safe, error_message)
        """
        try:
            self.sanitize(query)
            return True, None
        except ValueError as e:
            return False, str(e)