"""Tests for query complexity analyzer."""

import unittest
from search.query_analyzer import (
    QueryComplexityAnalyzer, ComplexityLevel, ComplexityMetrics
)


class TestQueryComplexityAnalyzer(unittest.TestCase):
    """Test the query complexity analyzer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = QueryComplexityAnalyzer()
    
    def test_empty_query(self):
        """Test analysis of empty query."""
        metrics = self.analyzer.analyze("")
        
        self.assertEqual(metrics.term_count, 0)
        self.assertEqual(metrics.operator_count, 0)
        self.assertEqual(metrics.nesting_depth, 0)
        self.assertEqual(metrics.wildcard_count, 0)
        self.assertEqual(metrics.phrase_count, 0)
        self.assertEqual(metrics.estimated_cost, 0.0)
        self.assertEqual(metrics.complexity_level, ComplexityLevel.SIMPLE)
        self.assertEqual(len(metrics.warnings), 0)
    
    def test_simple_query(self):
        """Test analysis of simple queries."""
        # Single term
        metrics = self.analyzer.analyze("test")
        self.assertEqual(metrics.term_count, 1)
        self.assertEqual(metrics.complexity_level, ComplexityLevel.SIMPLE)
        
        # Few terms
        metrics = self.analyzer.analyze("hello world python")
        self.assertEqual(metrics.term_count, 3)
        self.assertEqual(metrics.complexity_level, ComplexityLevel.SIMPLE)
    
    def test_operator_counting(self):
        """Test counting of boolean operators."""
        metrics = self.analyzer.analyze("test AND python OR javascript NOT typescript")
        self.assertEqual(metrics.operator_count, 3)
        self.assertEqual(metrics.term_count, 4)
        
        # Case insensitive
        metrics = self.analyzer.analyze("test and python or javascript")
        self.assertEqual(metrics.operator_count, 2)
    
    def test_nesting_depth(self):
        """Test calculation of nesting depth."""
        # No nesting
        metrics = self.analyzer.analyze("test python")
        self.assertEqual(metrics.nesting_depth, 0)
        
        # Single level
        metrics = self.analyzer.analyze("(test AND python)")
        self.assertEqual(metrics.nesting_depth, 1)
        
        # Multiple levels
        metrics = self.analyzer.analyze("((test AND python) OR (javascript AND typescript))")
        self.assertEqual(metrics.nesting_depth, 2)
        
        # Deep nesting
        metrics = self.analyzer.analyze("(((((deep)))))")
        self.assertEqual(metrics.nesting_depth, 5)
    
    def test_wildcard_counting(self):
        """Test counting of wildcard operators."""
        # Simple wildcards
        metrics = self.analyzer.analyze("test* python*")
        self.assertEqual(metrics.wildcard_count, 2)
        
        # Wildcards in quotes should not count
        metrics = self.analyzer.analyze('test* "not a wildcard*" real*')
        self.assertEqual(metrics.wildcard_count, 2)
        
        # Test escaped quotes don't affect wildcard counting
        metrics = self.analyzer.analyze('a* "phrase with \\" quote" b*')
        self.assertEqual(metrics.wildcard_count, 2)
        
        # Complex escaping scenario
        metrics = self.analyzer.analyze('test* "quoted \\"nested\\" text*" real*')
        self.assertEqual(metrics.wildcard_count, 2)
    
    def test_phrase_counting(self):
        """Test counting of quoted phrases."""
        # Single phrase
        metrics = self.analyzer.analyze('"hello world"')
        self.assertEqual(metrics.phrase_count, 1)
        
        # Multiple phrases
        metrics = self.analyzer.analyze('"hello world" AND "python programming"')
        self.assertEqual(metrics.phrase_count, 2)
        
        # Escaped quotes
        metrics = self.analyzer.analyze(r'"hello \"nested\" world"')
        self.assertEqual(metrics.phrase_count, 1)
    
    def test_special_char_counting(self):
        """Test counting of code-specific special characters."""
        # Programming symbols
        metrics = self.analyzer.analyze("$variable @decorator Class::method file-name.py")
        self.assertGreater(metrics.special_char_count, 0)
    
    def test_cost_calculation(self):
        """Test query cost calculation."""
        # Simple query should have low cost
        metrics = self.analyzer.analyze("simple test")
        self.assertLess(metrics.estimated_cost, 10)
        
        # Complex query should have higher cost
        complex_query = "test* AND (python OR javascript) AND \"exact phrase\" NOT typescript*"
        metrics = self.analyzer.analyze(complex_query)
        self.assertGreater(metrics.estimated_cost, 10)
        
        # Deep nesting increases cost exponentially
        deeply_nested = "(((((test)))))"
        metrics = self.analyzer.analyze(deeply_nested)
        self.assertGreater(metrics.estimated_cost, 50)  # 5^2 * 4 = 100 just for nesting
    
    def test_complexity_levels(self):
        """Test determination of complexity levels."""
        # Simple
        metrics = self.analyzer.analyze("simple query")
        self.assertEqual(metrics.complexity_level, ComplexityLevel.SIMPLE)
        
        # Moderate
        moderate_query = "test AND python OR javascript AND typescript"
        metrics = self.analyzer.analyze(moderate_query)
        self.assertIn(metrics.complexity_level, [ComplexityLevel.SIMPLE, ComplexityLevel.MODERATE])
        
        # Too complex - many terms
        many_terms = " ".join([f"term{i}" for i in range(60)])
        metrics = self.analyzer.analyze(many_terms)
        self.assertEqual(metrics.complexity_level, ComplexityLevel.TOO_COMPLEX)
        self.assertTrue(any("Too many terms" in w for w in metrics.warnings))
    
    def test_custom_thresholds(self):
        """Test analyzer with custom thresholds."""
        # Use default analyzer with custom thresholds passed per-call
        
        # Should be too complex with strict limits
        metrics = self.analyzer.analyze(
            "one two three four five six",
            max_terms=5,
            max_operators=2,
            max_wildcards=1,
            max_cost=10.0
        )
        self.assertEqual(metrics.complexity_level, ComplexityLevel.TOO_COMPLEX)
        
        # Should pass with fewer terms
        metrics = self.analyzer.analyze(
            "one two three",
            max_terms=5,
            max_operators=2,
            max_wildcards=1,
            max_cost=10.0
        )
        self.assertNotEqual(metrics.complexity_level, ComplexityLevel.TOO_COMPLEX)
    
    def test_is_too_complex(self):
        """Test quick complexity check."""
        # Simple query
        self.assertFalse(self.analyzer.is_too_complex("simple test"))
        
        # Complex query
        complex_query = " ".join([f"term{i}" for i in range(100)])
        self.assertTrue(self.analyzer.is_too_complex(complex_query))
    
    def test_warnings_generation(self):
        """Test that appropriate warnings are generated."""
        # Too many operators
        many_ops = " ".join([f"term{i} AND" for i in range(25)]) + " final"
        metrics = self.analyzer.analyze(many_ops)
        self.assertTrue(any("Too many operators" in w for w in metrics.warnings))
        
        # Too many wildcards
        many_wildcards = " ".join([f"term{i}*" for i in range(15)])
        metrics = self.analyzer.analyze(many_wildcards)
        self.assertTrue(any("Too many wildcards" in w for w in metrics.warnings))
        
        # Too deeply nested
        deep_nest = "(" * 7 + "test" + ")" * 7
        metrics = self.analyzer.analyze(deep_nest)
        self.assertTrue(any("Too deeply nested" in w for w in metrics.warnings))
    
    def test_suggest_simplification(self):
        """Test simplification suggestions."""
        # Too many wildcards
        suggestions = self.analyzer.suggest_simplification("a* b* c* d* e*")
        self.assertTrue(any("wildcard" in s.lower() for s in suggestions))
        
        # Too many operators
        complex_bool = " AND ".join([f"term{i}" for i in range(15)])
        suggestions = self.analyzer.suggest_simplification(complex_bool)
        self.assertTrue(any("boolean" in s.lower() for s in suggestions))
        
        # Deep nesting
        deep = "((((test))))"
        suggestions = self.analyzer.suggest_simplification(deep)
        self.assertTrue(any("nest" in s.lower() for s in suggestions))
        
        # Many terms
        many_terms = " ".join([f"word{i}" for i in range(30)])
        suggestions = self.analyzer.suggest_simplification(many_terms)
        self.assertTrue(any("fewer" in s.lower() for s in suggestions))
    
    def test_real_world_queries(self):
        """Test with real-world code search queries."""
        # Typical code search
        metrics = self.analyzer.analyze("function authenticate user login")
        self.assertEqual(metrics.complexity_level, ComplexityLevel.SIMPLE)
        
        # Complex code pattern search
        complex_code = '($variable OR @decorator) AND "class MyClass" AND (init* OR construct*)'
        metrics = self.analyzer.analyze(complex_code)
        self.assertIn(metrics.complexity_level, [ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX])
        
        # Overly complex search
        overcomplex = " OR ".join([f"func{i}*" for i in range(20)]) + " AND " + " OR ".join([f"class{i}" for i in range(20)])
        metrics = self.analyzer.analyze(overcomplex)
        self.assertEqual(metrics.complexity_level, ComplexityLevel.TOO_COMPLEX)


if __name__ == '__main__':
    unittest.main()