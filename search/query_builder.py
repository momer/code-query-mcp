"""FTS5 query builder with support for code-aware searching and fallback strategies."""

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
    
    def build_query(self, user_query: Optional[str]) -> str:
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
    
    def build_fallback_query(self, user_query: Optional[str]) -> str:
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
    
    def get_query_variants(self, user_query: Optional[str]) -> List[str]:
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
        additional = self.fallback_strategy.get_additional_variants(user_query)
        for variant in additional:
            if variant not in variants:
                variants.append(variant)
        
        return variants
    
    def normalize_query(self, user_query: str) -> str:
        """
        Normalize query for consistent grouping in analytics.
        
        Args:
            user_query: Raw query string from user
            
        Returns:
            Normalized query string
        """
        # Delegate to primary strategy if it has normalize method
        if hasattr(self.primary_strategy, 'normalize'):
            return self.primary_strategy.normalize(user_query)
        
        # Default normalization
        normalized = user_query.lower().strip()
        # Remove extra whitespace
        import re
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Sort terms unless query has operators
        has_operators = any(f' {op} ' in f' {normalized} ' for op in ['and', 'or', 'not', 'near'])
        if not has_operators:
            terms = normalized.split()
            normalized = ' '.join(sorted(terms))
        
        return normalized