"""Progressive search strategy implementation for optimal results."""

from typing import List, Callable, TypeVar, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class SearchStrategy:
    """Represents a search strategy with a name and execution function."""
    name: str
    description: str
    execute: Callable[[str], str]
    min_results_threshold: int = 0
    

class ProgressiveSearchStrategy:
    """Implements progressive search with multiple fallback strategies.
    
    This class manages a series of search strategies that are tried in order
    until sufficient results are found. Each strategy can be more relaxed
    than the previous one to ensure users get results.
    """
    
    def __init__(self, strategies: List[SearchStrategy]):
        """Initialize with ordered list of strategies.
        
        Args:
            strategies: List of strategies ordered from most to least specific
        """
        self.strategies = strategies
        
    def execute_search(
        self,
        query: str,
        search_func: Callable[[str], List[T]],
        min_results: int = 1,
        max_results: int = 50,
        deduplicate_func: Optional[Callable[[T], str]] = None
    ) -> List[T]:
        """Execute progressive search across strategies.
        
        Args:
            query: Original user query
            search_func: Function that executes search with transformed query
            min_results: Minimum results needed before trying next strategy
            max_results: Maximum total results to return
            deduplicate_func: Optional function to get deduplication key from result
            
        Returns:
            Combined results from all strategies that were executed
        """
        all_results = []
        seen_keys = set()
        
        for i, strategy in enumerate(self.strategies):
            # Check if we have enough results
            if len(all_results) >= min_results and i > 0:
                logger.debug(
                    f"Stopping at strategy {i} with {len(all_results)} results"
                )
                break
                
            try:
                # Transform query using strategy
                transformed_query = strategy.execute(query)
                logger.debug(
                    f"Trying strategy '{strategy.name}': {transformed_query}"
                )
                
                # Execute search
                results = search_func(transformed_query)
                
                # Deduplicate if function provided
                if deduplicate_func:
                    new_results = []
                    for result in results:
                        key = deduplicate_func(result)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            new_results.append(result)
                    results = new_results
                
                # Add to combined results
                all_results.extend(results)
                
                # Log strategy success
                logger.info(
                    f"Strategy '{strategy.name}' found {len(results)} results"
                )
                
                # Check if we have enough total results
                if len(all_results) >= max_results:
                    all_results = all_results[:max_results]
                    break
                    
            except Exception as e:
                logger.warning(
                    f"Strategy '{strategy.name}' failed: {e}"
                )
                continue
                
        return all_results
        
    def add_strategy(self, strategy: SearchStrategy, position: Optional[int] = None):
        """Add a new strategy to the list.
        
        Args:
            strategy: Strategy to add
            position: Position to insert at (None = append to end)
        """
        if position is None:
            self.strategies.append(strategy)
        else:
            self.strategies.insert(position, strategy)
            
    def remove_strategy(self, name: str) -> bool:
        """Remove a strategy by name.
        
        Args:
            name: Name of strategy to remove
            
        Returns:
            True if removed, False if not found
        """
        for i, strategy in enumerate(self.strategies):
            if strategy.name == name:
                self.strategies.pop(i)
                return True
        return False


def create_default_progressive_strategy() -> ProgressiveSearchStrategy:
    """Create the default progressive search strategy.
    
    Returns:
        ProgressiveSearchStrategy with standard fallback chain
    """
    strategies = [
        SearchStrategy(
            name="exact",
            description="Exact phrase and code-aware search",
            execute=lambda q: q,  # Use query as-is
            min_results_threshold=5
        ),
        SearchStrategy(
            name="fuzzy_terms",
            description="Individual terms with OR",
            execute=lambda q: " OR ".join(
                f'"{term}"' if any(c in term for c in ".-_$@:#") else term
                for term in q.split()
            ),
            min_results_threshold=3
        ),
        SearchStrategy(
            name="prefix_match",
            description="Prefix matching on terms",
            execute=lambda q: " OR ".join(
                f"{term}*" for term in q.split()
                if len(term) >= 3  # Only prefix match longer terms
            ),
            min_results_threshold=1
        ),
        SearchStrategy(
            name="partial_terms",
            description="Match any single term",
            execute=lambda q: " OR ".join(
                f'"{term}"' for term in q.split()
                if len(term) >= 2  # Skip very short terms
            ),
            min_results_threshold=0
        )
    ]
    
    return ProgressiveSearchStrategy(strategies)