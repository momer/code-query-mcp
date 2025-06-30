"""Tests for query utility functions."""

import unittest
from search.query_utils import (
    escape_special_chars,
    extract_terms,
    detect_operators,
    normalize_whitespace,
    is_phrase_query
)

class TestQueryUtils(unittest.TestCase):
    """Test query utility functions."""
    
    def test_escape_special_chars(self):
        """Test escaping of special characters."""
        # Quotes should be doubled
        self.assertEqual(escape_special_chars('test "quote"'), 'test ""quote""')
        self.assertEqual(escape_special_chars('"full quote"'), '""full quote""')
        
        # Other characters unchanged
        self.assertEqual(escape_special_chars('$var_name'), '$var_name')
        self.assertEqual(escape_special_chars('obj->method'), 'obj->method')
    
    def test_extract_terms(self):
        """Test term extraction from queries."""
        # Simple terms
        self.assertEqual(extract_terms("one two three"), ["one", "two", "three"])
        
        # With quoted phrases
        self.assertEqual(
            extract_terms('search "exact phrase" term'),
            ["exact phrase", "search", "term"]
        )
        
        # Multiple phrases
        self.assertEqual(
            extract_terms('"first phrase" and "second phrase"'),
            ["first phrase", "second phrase", "and"]
        )
        
        # Empty query
        self.assertEqual(extract_terms(""), [])
        self.assertEqual(extract_terms("   "), [])
    
    def test_detect_operators(self):
        """Test FTS5 operator detection."""
        # Single operators
        self.assertEqual(detect_operators("term1 AND term2"), {"AND"})
        self.assertEqual(detect_operators("term1 OR term2"), {"OR"})
        self.assertEqual(detect_operators("term NOT other"), {"NOT"})
        self.assertEqual(detect_operators("NEAR(term1 term2)"), {"NEAR"})
        
        # Multiple operators
        self.assertEqual(
            detect_operators("term1 AND term2 OR term3"),
            {"AND", "OR"}
        )
        
        # No operators
        self.assertEqual(detect_operators("just regular terms"), set())
        
        # Case sensitive
        self.assertEqual(detect_operators("and or not"), set())
    
    def test_normalize_whitespace(self):
        """Test whitespace normalization."""
        self.assertEqual(normalize_whitespace("  spaced   out  "), "spaced out")
        self.assertEqual(normalize_whitespace("tabs\there"), "tabs here")
        self.assertEqual(normalize_whitespace("newline\nhere"), "newline here")
        self.assertEqual(normalize_whitespace("normal spacing"), "normal spacing")
    
    def test_is_phrase_query(self):
        """Test phrase query detection."""
        self.assertTrue(is_phrase_query('"exact phrase"'))
        self.assertTrue(is_phrase_query('"another one"'))
        
        self.assertFalse(is_phrase_query('not "a phrase"'))
        self.assertFalse(is_phrase_query('"partial phrase'))
        self.assertFalse(is_phrase_query('regular query'))
        self.assertFalse(is_phrase_query(''))
    


if __name__ == '__main__':
    unittest.main()