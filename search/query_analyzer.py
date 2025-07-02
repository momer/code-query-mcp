"""Query complexity analyzer for preventing DoS through complex queries."""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class ComplexityLevel(Enum):
    """Query complexity levels."""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    TOO_COMPLEX = "too_complex"


@dataclass
class ComplexityMetrics:
    """Metrics for query complexity analysis."""
    term_count: int
    operator_count: int
    nesting_depth: int
    wildcard_count: int
    phrase_count: int
    special_char_count: int
    estimated_cost: float
    complexity_level: ComplexityLevel
    warnings: List[str]


class QueryComplexityAnalyzer:
    """Analyzes FTS5 query complexity to prevent DoS attacks.
    
    This analyzer examines queries for patterns that could cause
    excessive resource usage in FTS5 searches.
    """
    
    # Complexity thresholds
    DEFAULT_MAX_TERMS = 50
    DEFAULT_MAX_OPERATORS = 20
    DEFAULT_MAX_NESTING = 5
    DEFAULT_MAX_WILDCARDS = 10
    DEFAULT_MAX_COST = 100.0
    
    # Cost weights for different query features
    TERM_COST = 1.0
    OPERATOR_COST = 2.0
    WILDCARD_COST = 5.0
    PHRASE_COST = 3.0
    NESTED_GROUP_COST = 4.0
    
    def __init__(
        self,
        max_terms: int = DEFAULT_MAX_TERMS,
        max_operators: int = DEFAULT_MAX_OPERATORS,
        max_nesting: int = DEFAULT_MAX_NESTING,
        max_wildcards: int = DEFAULT_MAX_WILDCARDS,
        max_cost: float = DEFAULT_MAX_COST
    ):
        """Initialize analyzer with thresholds.
        
        Args:
            max_terms: Maximum number of search terms
            max_operators: Maximum number of boolean operators
            max_nesting: Maximum parentheses nesting depth
            max_wildcards: Maximum number of wildcard operators
            max_cost: Maximum estimated query cost
        """
        self.max_terms = max_terms
        self.max_operators = max_operators
        self.max_nesting = max_nesting
        self.max_wildcards = max_wildcards
        self.max_cost = max_cost
        
    def analyze(
        self, 
        query: str,
        max_terms: Optional[int] = None,
        max_operators: Optional[int] = None,
        max_nesting: Optional[int] = None,
        max_wildcards: Optional[int] = None,
        max_cost: Optional[float] = None
    ) -> ComplexityMetrics:
        """Analyze query complexity.
        
        Args:
            query: FTS5 query string to analyze
            max_terms: Maximum number of search terms (overrides instance default)
            max_operators: Maximum number of boolean operators (overrides instance default)
            max_nesting: Maximum parentheses nesting depth (overrides instance default)
            max_wildcards: Maximum number of wildcard operators (overrides instance default)
            max_cost: Maximum estimated query cost (overrides instance default)
            
        Returns:
            ComplexityMetrics with analysis results
        """
        if not query:
            return ComplexityMetrics(
                term_count=0,
                operator_count=0,
                nesting_depth=0,
                wildcard_count=0,
                phrase_count=0,
                special_char_count=0,
                estimated_cost=0.0,
                complexity_level=ComplexityLevel.SIMPLE,
                warnings=[]
            )
        
        # Use provided thresholds or fall back to instance defaults
        max_terms = max_terms if max_terms is not None else self.max_terms
        max_operators = max_operators if max_operators is not None else self.max_operators
        max_nesting = max_nesting if max_nesting is not None else self.max_nesting
        max_wildcards = max_wildcards if max_wildcards is not None else self.max_wildcards
        max_cost = max_cost if max_cost is not None else self.max_cost
        
        # Count various query components
        term_count = self._count_terms(query)
        operator_count = self._count_operators(query)
        nesting_depth = self._calculate_nesting_depth(query)
        wildcard_count = self._count_wildcards(query)
        phrase_count = self._count_phrases(query)
        special_char_count = self._count_special_chars(query)
        
        # Calculate estimated cost
        cost = self._calculate_cost(
            term_count=term_count,
            operator_count=operator_count,
            nesting_depth=nesting_depth,
            wildcard_count=wildcard_count,
            phrase_count=phrase_count
        )
        
        # Determine complexity level and warnings
        complexity_level, warnings = self._determine_complexity(
            term_count=term_count,
            operator_count=operator_count,
            nesting_depth=nesting_depth,
            wildcard_count=wildcard_count,
            cost=cost,
            max_terms=max_terms,
            max_operators=max_operators,
            max_nesting=max_nesting,
            max_wildcards=max_wildcards,
            max_cost=max_cost
        )
        
        return ComplexityMetrics(
            term_count=term_count,
            operator_count=operator_count,
            nesting_depth=nesting_depth,
            wildcard_count=wildcard_count,
            phrase_count=phrase_count,
            special_char_count=special_char_count,
            estimated_cost=cost,
            complexity_level=complexity_level,
            warnings=warnings
        )
        
    def is_too_complex(
        self, 
        query: str,
        max_terms: Optional[int] = None,
        max_operators: Optional[int] = None,
        max_nesting: Optional[int] = None,
        max_wildcards: Optional[int] = None,
        max_cost: Optional[float] = None
    ) -> bool:
        """Quick check if query is too complex.
        
        Args:
            query: FTS5 query string
            max_terms: Maximum number of search terms (overrides instance default)
            max_operators: Maximum number of boolean operators (overrides instance default)
            max_nesting: Maximum parentheses nesting depth (overrides instance default)
            max_wildcards: Maximum number of wildcard operators (overrides instance default)
            max_cost: Maximum estimated query cost (overrides instance default)
            
        Returns:
            True if query exceeds complexity thresholds
        """
        metrics = self.analyze(
            query,
            max_terms=max_terms,
            max_operators=max_operators,
            max_nesting=max_nesting,
            max_wildcards=max_wildcards,
            max_cost=max_cost
        )
        return metrics.complexity_level == ComplexityLevel.TOO_COMPLEX
        
    def _count_terms(self, query: str) -> int:
        """Count search terms in query."""
        # Remove operators and special syntax
        cleaned = re.sub(r'\b(AND|OR|NOT)\b', ' ', query, flags=re.IGNORECASE)
        cleaned = re.sub(r'[()"]', ' ', cleaned)
        
        # Split and count non-empty terms
        terms = [t for t in cleaned.split() if t and not t.isspace()]
        return len(terms)
        
    def _count_operators(self, query: str) -> int:
        """Count boolean operators."""
        operators = re.findall(r'\b(AND|OR|NOT)\b', query, flags=re.IGNORECASE)
        return len(operators)
        
    def _calculate_nesting_depth(self, query: str) -> int:
        """Calculate maximum parentheses nesting depth."""
        max_depth = 0
        current_depth = 0
        
        for char in query:
            if char == '(':
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif char == ')':
                current_depth = max(0, current_depth - 1)
                
        return max_depth
        
    def _count_wildcards(self, query: str) -> int:
        """Count wildcard operators."""
        # Count asterisks not inside quotes
        in_quotes = False
        wildcard_count = 0
        escaped = False
        
        for i, char in enumerate(query):
            if escaped:
                # Skip this character, it's escaped
                escaped = False
                continue
                
            if char == '\\':
                # Next character is escaped
                escaped = True
            elif char == '"':
                # Toggle quote state only if not escaped
                in_quotes = not in_quotes
            elif char == '*' and not in_quotes:
                wildcard_count += 1
                
        return wildcard_count
        
    def _count_phrases(self, query: str) -> int:
        """Count quoted phrases."""
        # Match quoted strings, accounting for escaped quotes
        phrases = re.findall(r'"([^"\\]|\\.)*"', query)
        return len(phrases)
        
    def _count_special_chars(self, query: str) -> int:
        """Count code-specific special characters."""
        # Count programming-related special chars
        special_chars = re.findall(r'[$@#:._-]', query)
        return len(special_chars)
        
    def _calculate_cost(
        self,
        term_count: int,
        operator_count: int,
        nesting_depth: int,
        wildcard_count: int,
        phrase_count: int
    ) -> float:
        """Calculate estimated query cost."""
        cost = (
            term_count * self.TERM_COST +
            operator_count * self.OPERATOR_COST +
            wildcard_count * self.WILDCARD_COST +
            phrase_count * self.PHRASE_COST +
            (nesting_depth ** 2) * self.NESTED_GROUP_COST  # Exponential cost for deep nesting
        )
        return cost
        
    def _determine_complexity(
        self,
        term_count: int,
        operator_count: int,
        nesting_depth: int,
        wildcard_count: int,
        cost: float,
        max_terms: int,
        max_operators: int,
        max_nesting: int,
        max_wildcards: int,
        max_cost: float
    ) -> Tuple[ComplexityLevel, List[str]]:
        """Determine complexity level and generate warnings."""
        warnings = []
        
        # Check individual limits
        if term_count > max_terms:
            warnings.append(f"Too many terms ({term_count} > {max_terms})")
            
        if operator_count > max_operators:
            warnings.append(f"Too many operators ({operator_count} > {max_operators})")
            
        if nesting_depth > max_nesting:
            warnings.append(f"Too deeply nested ({nesting_depth} > {max_nesting})")
            
        if wildcard_count > max_wildcards:
            warnings.append(f"Too many wildcards ({wildcard_count} > {max_wildcards})")
            
        if cost > max_cost:
            warnings.append(f"Query too expensive (cost {cost:.1f} > {max_cost})")
        
        # Determine overall complexity
        if warnings:
            return ComplexityLevel.TOO_COMPLEX, warnings
        elif cost > max_cost * 0.7:
            return ComplexityLevel.COMPLEX, ["Query approaching complexity limits"]
        elif cost > max_cost * 0.3:
            return ComplexityLevel.MODERATE, []
        else:
            return ComplexityLevel.SIMPLE, []
            
    def suggest_simplification(self, query: str) -> List[str]:
        """Suggest ways to simplify a complex query.
        
        Args:
            query: Complex query to analyze
            
        Returns:
            List of simplification suggestions
        """
        metrics = self.analyze(query)
        suggestions = []
        
        if metrics.wildcard_count > 3:
            suggestions.append("Reduce wildcard usage - they are expensive to process")
            
        if metrics.operator_count > 10:
            suggestions.append("Simplify boolean logic - too many AND/OR operators")
            
        if metrics.nesting_depth > 2:
            suggestions.append("Flatten nested groups - deep nesting increases complexity")
            
        if metrics.term_count > 20:
            suggestions.append("Use fewer search terms - try to be more specific")
            
        if not suggestions and metrics.complexity_level == ComplexityLevel.TOO_COMPLEX:
            suggestions.append("Query is too complex - try breaking it into smaller searches")
            
        return suggestions