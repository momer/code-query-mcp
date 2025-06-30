"""Tests for fixes identified by zen review."""

import unittest
from search.query_builder import FTS5QueryBuilder
from search.query_strategies import CodeAwareQueryStrategy

class TestZenFixes(unittest.TestCase):
    """Test fixes for issues identified by zen review."""
    
    def setUp(self):
        """Set up test builder."""
        self.builder = FTS5QueryBuilder()
        self.strategy = CodeAwareQueryStrategy()
    
    def test_quoted_phrases_preserved(self):
        """Test CRITICAL fix: quoted phrases are preserved in queries."""
        # Test that phrases extracted by extract_terms are re-quoted
        result = self.builder.build_query('search "exact phrase" term')
        self.assertIn('"exact phrase"', result)
        self.assertIn('search', result)
        self.assertIn('term', result)
        
        # Test multi-word phrase
        result = self.builder.build_query('find "user authentication system"')
        self.assertIn('"user authentication system"', result)
    
    def test_advanced_fts5_operators(self):
        """Test HIGH fix: advanced FTS5 operators like NEAR() work correctly."""
        # Test NEAR function
        result = self.strategy._process_advanced_query('NEAR(term1 term2, 10)')
        self.assertEqual(result, 'NEAR(term1 term2, 10)')
        
        # Test mixed query with NEAR
        result = self.strategy._process_advanced_query('user NEAR(login session, 5) auth')
        self.assertIn('NEAR(login session, 5)', result)
        self.assertIn('user', result)
        self.assertIn('auth', result)
        
        # Test code patterns with NEAR
        result = self.strategy._process_advanced_query('$user NEAR(get_id method, 3)')
        self.assertIn('"$user"', result)
        self.assertIn('NEAR(get_id method, 3)', result)
    
    def test_operators_case_insensitive(self):
        """Test that operators work regardless of case."""
        # The regex should handle case-insensitive operators
        result = self.strategy._process_advanced_query('term1 and term2 OR term3')
        # Should preserve the operators as found
        self.assertIn('and', result)
        self.assertIn('OR', result)


if __name__ == '__main__':
    unittest.main()