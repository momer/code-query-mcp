"""Tests for tokenizer configuration and code pattern detection."""

import unittest
from search.tokenizer_config import is_code_pattern, TOKENIZER_CHARS, CODE_OPERATORS

class TestTokenizerConfig(unittest.TestCase):
    """Test tokenizer configuration functionality."""
    
    def test_code_pattern_detection(self):
        """Test code pattern detection."""
        # Special character patterns
        self.assertTrue(is_code_pattern("$var"))
        self.assertTrue(is_code_pattern("_private"))
        self.assertTrue(is_code_pattern("my_function"))
        self.assertTrue(is_code_pattern("obj->method"))
        self.assertTrue(is_code_pattern("Class::static"))
        self.assertTrue(is_code_pattern("@decorator"))
        self.assertTrue(is_code_pattern("#define"))
        
        # Case patterns
        self.assertTrue(is_code_pattern("camelCase"))
        self.assertTrue(is_code_pattern("snake_case"))
        
        # Regular words
        self.assertFalse(is_code_pattern("regular"))
        self.assertFalse(is_code_pattern("word"))
        self.assertFalse(is_code_pattern("UPPERCASE"))
    
    def test_tokenizer_chars(self):
        """Test tokenizer character constants."""
        # Verify expected characters are present
        self.assertIn('_', TOKENIZER_CHARS)
        self.assertIn('$', TOKENIZER_CHARS)
        self.assertIn('.', TOKENIZER_CHARS)
        self.assertIn('@', TOKENIZER_CHARS)
        # Note: -> and :: are multi-char sequences in the string
        self.assertIn('->', TOKENIZER_CHARS)
        self.assertIn(':', TOKENIZER_CHARS)  # Part of ::
        self.assertIn('#', TOKENIZER_CHARS)
    
    def test_code_operators(self):
        """Test code operator constants."""
        # Verify common operators
        self.assertIn('->', CODE_OPERATORS)
        self.assertIn('::', CODE_OPERATORS)
        self.assertIn('.', CODE_OPERATORS)
        self.assertIn('_', CODE_OPERATORS)
        self.assertIn('$', CODE_OPERATORS)
    
    def test_edge_cases(self):
        """Test edge cases for code pattern detection."""
        # Empty string
        self.assertFalse(is_code_pattern(""))
        
        # Single special char
        self.assertTrue(is_code_pattern("$"))
        self.assertTrue(is_code_pattern("_"))
        
        # Mixed patterns
        self.assertTrue(is_code_pattern("$camelCase"))
        self.assertTrue(is_code_pattern("_snake_case"))
        self.assertTrue(is_code_pattern("observable$"))
        
        # Numbers with patterns
        self.assertTrue(is_code_pattern("var_123"))
        self.assertTrue(is_code_pattern("$123"))


if __name__ == '__main__':
    unittest.main()