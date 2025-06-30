"""Tests for query building strategies."""

import unittest
from search.query_strategies import (
    DefaultQueryStrategy,
    CodeAwareQueryStrategy,
    FallbackStrategy
)

class TestQueryStrategies(unittest.TestCase):
    """Test different query building strategies."""
    
    def test_default_strategy(self):
        """Test basic default strategy."""
        strategy = DefaultQueryStrategy()
        
        # Simple queries
        self.assertEqual(strategy.build("test"), "test")
        self.assertEqual(strategy.build("multiple words"), "multiple words")
        
        # Should escape quotes
        self.assertEqual(strategy.build('with "quotes"'), 'with ""quotes""')
    
    def test_code_aware_strategy(self):
        """Test code-aware query building."""
        strategy = CodeAwareQueryStrategy()
        
        # Code patterns become phrases
        self.assertEqual(strategy.build("$var"), '"$var"')
        self.assertEqual(strategy.build("my_func"), '"my_func"')
        self.assertEqual(strategy.build("obj->prop"), '"obj->prop"')
        self.assertEqual(strategy.build("Class::method"), '"Class::method"')
        
        # Regular terms stay separate
        self.assertEqual(strategy.build("login user"), "login user")
        
        # Preserve FTS5 operators
        self.assertEqual(strategy.build("login OR signup"), "login OR signup")
        self.assertEqual(strategy.build("auth* NOT test"), "auth* NOT test")
        
        # Preserve quoted phrases
        self.assertEqual(strategy.build('"exact match"'), '"exact match"')
    
    def test_code_aware_advanced_queries(self):
        """Test advanced query handling in code-aware strategy."""
        strategy = CodeAwareQueryStrategy()
        
        # Mixed operators and terms
        query = strategy.build("getUserById OR get_user_by_id")
        self.assertIn("OR", query)
        self.assertIn('"get_user_by_id"', query)  # Code pattern should be quoted
    
    def test_fallback_strategies(self):
        """Test various fallback approaches."""
        strategy = FallbackStrategy()
        
        # Default build uses phrase search
        self.assertEqual(strategy.build("multi word"), '"multi word"')
        
        # Phrase fallback
        self.assertEqual(strategy.phrase_search_fallback("test query"), '"test query"')
        
        # Prefix fallback
        self.assertEqual(strategy.prefix_match_fallback("user log"), "user* log*")
        self.assertEqual(strategy.prefix_match_fallback("auth*"), "auth*")  # Don't double *
        
        # OR fallback
        self.assertEqual(strategy.or_search_fallback("user login auth"), "user OR login OR auth")
        self.assertEqual(strategy.or_search_fallback("single"), "single")  # Single term unchanged
        
        # Keyword extraction
        result = strategy.keyword_extraction_fallback("the user authentication system")
        # Result should be an OR query without stop words
        self.assertIn("OR", result)
        self.assertIn("user", result)
        self.assertIn("authentication", result)
        self.assertIn("system", result)
        # "the" should be filtered out as a stop word
        words = result.split()
        self.assertNotIn("the", words)
    
    def test_fallback_additional_variants(self):
        """Test generation of additional fallback variants."""
        strategy = FallbackStrategy()
        
        # Multiple terms should generate OR variant
        variants = strategy.get_additional_variants("user login system")
        self.assertTrue(any("OR" in v for v in variants))
        
        # Should generate prefix variant
        self.assertTrue(any("*" in v for v in variants))
        
        # Long queries should have keyword extraction
        long_query = "find the user authentication and authorization system"
        variants = strategy.get_additional_variants(long_query)
        self.assertTrue(len(variants) > 2)
    
    def test_stop_word_handling(self):
        """Test stop word filtering in keyword extraction."""
        strategy = FallbackStrategy()
        
        # Code patterns with stop words should be preserved
        result = strategy.keyword_extraction_fallback("the $in_variable")
        self.assertIn("$in_variable", result)  # Code pattern preserved despite "in"
        
        # Regular stop words filtered
        result = strategy.keyword_extraction_fallback("the quick brown fox")
        self.assertNotIn("the", result)


if __name__ == '__main__':
    unittest.main()