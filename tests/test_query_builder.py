"""Tests for FTS5QueryBuilder."""

import unittest
from search.query_builder import FTS5QueryBuilder
from search.query_strategies import DefaultQueryStrategy

class TestFTS5QueryBuilder(unittest.TestCase):
    """Test FTS5QueryBuilder functionality."""
    
    def setUp(self):
        """Set up test builder."""
        self.builder = FTS5QueryBuilder()
    
    def test_empty_query(self):
        """Test handling of empty queries."""
        self.assertEqual(self.builder.build_query(""), '""')
        self.assertEqual(self.builder.build_query("   "), '""')
        self.assertEqual(self.builder.build_query(None), '""')
    
    def test_simple_query(self):
        """Test basic query building."""
        self.assertEqual(self.builder.build_query("login"), "login")
        self.assertEqual(self.builder.build_query("user auth"), "user auth")
    
    def test_code_pattern_detection(self):
        """Test code pattern queries become phrases."""
        # Variables and identifiers with special chars
        self.assertEqual(self.builder.build_query("$httpClient"), '"$httpClient"')
        self.assertEqual(self.builder.build_query("my_function"), '"my_function"')
        self.assertEqual(self.builder.build_query("obj->method"), '"obj->method"')
        self.assertEqual(self.builder.build_query("Class::method"), '"Class::method"')
        self.assertEqual(self.builder.build_query("@decorator"), '"@decorator"')
        self.assertEqual(self.builder.build_query("#identifier"), '"#identifier"')
    
    def test_fts5_operator_preservation(self):
        """Test that FTS5 operators are preserved."""
        self.assertEqual(self.builder.build_query("login OR signup"), "login OR signup")
        self.assertEqual(self.builder.build_query("user AND auth"), "user AND auth")
        self.assertEqual(self.builder.build_query("login NOT logout"), "login NOT logout")
        self.assertEqual(self.builder.build_query("auth*"), "auth*")
    
    def test_phrase_queries(self):
        """Test phrase query handling."""
        self.assertEqual(self.builder.build_query('"exact phrase"'), '"exact phrase"')
        self.assertEqual(self.builder.build_query('"user authentication"'), '"user authentication"')
    
    def test_fallback_generation(self):
        """Test fallback query generation."""
        primary = self.builder.build_query("complex query")
        fallback = self.builder.build_fallback_query("complex query")
        self.assertNotEqual(primary, fallback)
        self.assertEqual(fallback, '"complex query"')
        
        # Code patterns should be preserved in fallback
        self.assertEqual(self.builder.build_fallback_query("my_function"), '"my_function"')
    
    def test_query_variants(self):
        """Test generation of query variants."""
        variants = self.builder.get_query_variants("user authentication system")
        self.assertGreaterEqual(len(variants), 2)
        self.assertNotEqual(variants[0], variants[1])
        
        # First variant should be the primary query
        self.assertEqual(variants[0], self.builder.build_query("user authentication system"))
        
        # Should include phrase search as fallback
        self.assertIn('"user authentication system"', variants)
    
    def test_special_char_escaping(self):
        """Test escaping of special characters."""
        # Quotes in the middle of text are extracted as phrases
        result = self.builder.build_query('search "with quotes"')
        # The query builder extracts "with quotes" as a phrase
        self.assertIn('with quotes', result)
        self.assertIn('search', result)
    
    def test_mixed_queries(self):
        """Test queries with mixed patterns."""
        # Code pattern with regular terms
        query = self.builder.build_query("find $variable in code")
        # Should preserve the code pattern
        self.assertIn('"$variable"', query)
    
    def test_custom_strategy(self):
        """Test using custom strategy."""
        builder = FTS5QueryBuilder(primary_strategy=DefaultQueryStrategy())
        result = builder.build_query("test query")
        self.assertEqual(result, "test query")


if __name__ == '__main__':
    unittest.main()