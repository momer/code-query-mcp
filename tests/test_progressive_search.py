"""Tests for progressive search strategy."""

import unittest
from unittest.mock import Mock
from typing import List

from search.progressive_search import (
    ProgressiveSearchStrategy, SearchStrategy, create_default_progressive_strategy
)


class TestProgressiveSearchStrategy(unittest.TestCase):
    """Test the progressive search strategy implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test strategies
        self.strategies = [
            SearchStrategy(
                name="exact",
                description="Exact match",
                execute=lambda q: f'"{q}"',
                min_results_threshold=3
            ),
            SearchStrategy(
                name="fuzzy",
                description="Fuzzy match",
                execute=lambda q: q.replace(" ", " OR "),
                min_results_threshold=1
            ),
            SearchStrategy(
                name="wildcard",
                description="Wildcard match",
                execute=lambda q: f"{q}*",
                min_results_threshold=0
            )
        ]
        
        self.progressive = ProgressiveSearchStrategy(self.strategies)
    
    def test_single_strategy_success(self):
        """Test when first strategy returns enough results."""
        # Mock search function that returns results for exact match
        def search_func(query):
            if query == '"test query"':
                return ["result1", "result2", "result3", "result4"]
            return []
        
        results = self.progressive.execute_search(
            "test query",
            search_func,
            min_results=3
        )
        
        # Should only use first strategy
        self.assertEqual(len(results), 4)
        self.assertEqual(results, ["result1", "result2", "result3", "result4"])
    
    def test_fallback_to_second_strategy(self):
        """Test fallback when first strategy doesn't return enough results."""
        # Mock search function
        def search_func(query):
            if query == '"test query"':
                return ["result1"]  # Not enough
            elif query == "test OR query":
                return ["result2", "result3", "result4"]
            return []
        
        results = self.progressive.execute_search(
            "test query",
            search_func,
            min_results=3
        )
        
        # Should combine results from both strategies
        self.assertEqual(len(results), 4)
        self.assertEqual(results, ["result1", "result2", "result3", "result4"])
    
    def test_all_strategies_tried(self):
        """Test that all strategies are tried if needed."""
        # Mock search function
        call_count = {"count": 0}
        queries_tried = []
        
        def search_func(query):
            call_count["count"] += 1
            queries_tried.append(query)
            return [f"result{call_count['count']}"]  # One result per strategy
        
        results = self.progressive.execute_search(
            "test",
            search_func,
            min_results=5  # More than any strategy will return
        )
        
        # All three strategies should be tried
        self.assertEqual(call_count["count"], 3)
        self.assertEqual(len(queries_tried), 3)
        self.assertEqual(queries_tried, ['"test"', 'test', 'test*'])
        self.assertEqual(results, ["result1", "result2", "result3"])
    
    def test_deduplication(self):
        """Test deduplication across strategies."""
        # Mock search function that returns overlapping results
        def search_func(query):
            if query == '"test"':
                return [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
            elif query == "test":  # Second strategy doesn't transform single word
                return [{"id": 2, "name": "b"}, {"id": 3, "name": "c"}]
            return []
        
        # Deduplicate by id
        results = self.progressive.execute_search(
            "test",
            search_func,
            min_results=4,  # Force it to try multiple strategies
            deduplicate_func=lambda r: r["id"]
        )
        
        # Should have 3 unique results
        self.assertEqual(len(results), 3)
        ids = [r["id"] for r in results]
        self.assertEqual(ids, [1, 2, 3])
    
    def test_max_results_limit(self):
        """Test that max_results is respected."""
        # Mock search function that returns many results
        def search_func(query):
            return list(range(100))  # 100 results
        
        results = self.progressive.execute_search(
            "test",
            search_func,
            max_results=10
        )
        
        # Should stop at max_results
        self.assertEqual(len(results), 10)
        self.assertEqual(results, list(range(10)))
    
    def test_strategy_failure_handling(self):
        """Test that failures in strategies are handled gracefully."""
        # Mock search function that fails for certain queries
        def search_func(query):
            if query == '"test"':
                raise Exception("Search failed")
            elif query == "test":
                return ["result1", "result2"]
            return []
        
        # Should continue to next strategy on failure
        results = self.progressive.execute_search(
            "test",
            search_func,
            min_results=1
        )
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results, ["result1", "result2"])
    
    def test_add_strategy(self):
        """Test adding a new strategy."""
        new_strategy = SearchStrategy(
            name="new",
            description="New strategy",
            execute=lambda q: q
        )
        
        # Add at specific position
        self.progressive.add_strategy(new_strategy, position=1)
        self.assertEqual(len(self.progressive.strategies), 4)
        self.assertEqual(self.progressive.strategies[1].name, "new")
        
        # Add at end
        end_strategy = SearchStrategy(
            name="end",
            description="End strategy",
            execute=lambda q: q
        )
        self.progressive.add_strategy(end_strategy)
        self.assertEqual(len(self.progressive.strategies), 5)
        self.assertEqual(self.progressive.strategies[-1].name, "end")
    
    def test_remove_strategy(self):
        """Test removing a strategy."""
        # Remove existing
        result = self.progressive.remove_strategy("fuzzy")
        self.assertTrue(result)
        self.assertEqual(len(self.progressive.strategies), 2)
        self.assertEqual(
            [s.name for s in self.progressive.strategies],
            ["exact", "wildcard"]
        )
        
        # Remove non-existent
        result = self.progressive.remove_strategy("nonexistent")
        self.assertFalse(result)
        self.assertEqual(len(self.progressive.strategies), 2)


class TestDefaultProgressiveStrategy(unittest.TestCase):
    """Test the default progressive strategy creation."""
    
    def test_create_default_strategy(self):
        """Test that default strategy is created properly."""
        strategy = create_default_progressive_strategy()
        
        self.assertIsInstance(strategy, ProgressiveSearchStrategy)
        self.assertEqual(len(strategy.strategies), 4)
        
        # Check strategy names
        names = [s.name for s in strategy.strategies]
        self.assertEqual(names, ["exact", "fuzzy_terms", "prefix_match", "partial_terms"])
    
    def test_default_strategy_transformations(self):
        """Test query transformations in default strategies."""
        strategy = create_default_progressive_strategy()
        
        # Test exact strategy
        exact = strategy.strategies[0]
        self.assertEqual(exact.execute("test query"), "test query")
        
        # Test fuzzy_terms strategy
        fuzzy = strategy.strategies[1]
        self.assertEqual(fuzzy.execute("test query"), "test OR query")
        self.assertEqual(fuzzy.execute("$var test"), '"$var" OR test')
        
        # Test prefix_match strategy
        prefix = strategy.strategies[2]
        self.assertEqual(prefix.execute("test query"), "test* OR query*")
        self.assertEqual(prefix.execute("a bb test"), "test*")  # Skips short terms
        
        # Test partial_terms strategy
        partial = strategy.strategies[3]
        self.assertEqual(partial.execute("test query x"), '"test" OR "query"')  # Skips 'x'


if __name__ == '__main__':
    unittest.main()