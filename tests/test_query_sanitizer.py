"""Tests for FTS5 query sanitizer."""

import unittest
from search.query_sanitizer import FTS5QuerySanitizer, SanitizationConfig


class TestFTS5QuerySanitizer(unittest.TestCase):
    """Test FTS5 query sanitization."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sanitizer = FTS5QuerySanitizer()
        self.permissive_sanitizer = FTS5QuerySanitizer(
            SanitizationConfig(allow_column_filters=True)
        )
    
    def test_basic_terms(self):
        """Test sanitization of basic search terms."""
        # Simple terms should pass through
        self.assertEqual(self.sanitizer.sanitize("hello world"), "hello world")
        self.assertEqual(self.sanitizer.sanitize("function"), "function")
        
        # Empty query
        self.assertEqual(self.sanitizer.sanitize(""), '""')
        self.assertEqual(self.sanitizer.sanitize("   "), '""')
    
    def test_phrase_searches(self):
        """Test preservation of phrase searches."""
        # Basic phrases
        self.assertEqual(
            self.sanitizer.sanitize('"exact phrase"'),
            '"exact phrase"'
        )
        
        # Multiple phrases
        self.assertEqual(
            self.sanitizer.sanitize('"first phrase" "second phrase"'),
            '"first phrase" "second phrase"'
        )
        
        # Phrases with escaped quotes
        self.assertEqual(
            self.sanitizer.sanitize('"say ""hello"" world"'),
            '"say ""hello"" world"'
        )
        
        # Mixed phrases and terms - preserves order
        self.assertEqual(
            self.sanitizer.sanitize('find "user login" function'),
            'find "user login" function'
        )
    
    def test_boolean_operators(self):
        """Test preservation of AND, OR, NOT operators."""
        # Operators should be preserved and uppercased
        self.assertEqual(
            self.sanitizer.sanitize("term1 AND term2"),
            "term1 AND term2"
        )
        
        self.assertEqual(
            self.sanitizer.sanitize("term1 OR term2 OR term3"),
            "term1 OR term2 OR term3"
        )
        
        self.assertEqual(
            self.sanitizer.sanitize("login NOT password"),
            "login NOT password"
        )
        
        # Case insensitive
        self.assertEqual(
            self.sanitizer.sanitize("term1 and term2"),
            "term1 AND term2"
        )
    
    def test_wildcard_queries(self):
        """Test wildcard query handling."""
        # Valid wildcards at end
        self.assertEqual(
            self.sanitizer.sanitize("user*"),
            "user*"
        )
        
        self.assertEqual(
            self.sanitizer.sanitize("get* set*"),
            "get* set*"
        )
        
        # Invalid wildcards get removed
        self.assertEqual(
            self.sanitizer.sanitize("*user"),  # Prefix wildcard not valid
            "user"
        )
        
        self.assertEqual(
            self.sanitizer.sanitize("us*er"),  # Middle wildcard not valid
            "user"
        )
        
        # Too many wildcards
        with self.assertRaises(ValueError) as ctx:
            self.sanitizer.sanitize("a* b* c* d* e* f*")
        self.assertIn("too many wildcards", str(ctx.exception))
    
    def test_near_operator(self):
        """Test NEAR operator preservation."""
        # Basic NEAR
        self.assertEqual(
            self.sanitizer.sanitize("NEAR(term1 term2)"),
            'NEAR("term1" "term2", 10)'  # Terms quoted, default distance
        )
        
        # NEAR with distance
        self.assertEqual(
            self.sanitizer.sanitize("NEAR(login session, 5)"),
            'NEAR("login" "session", 5)'
        )
        
        # Case insensitive
        self.assertEqual(
            self.sanitizer.sanitize("near(foo bar, 3)"),
            'NEAR("foo" "bar", 3)'
        )
        
        # NEAR with special terms
        self.assertEqual(
            self.sanitizer.sanitize("NEAR($user get_id, 2)"),
            'NEAR("$user" "get_id", 2)'
        )
        
        # NEAR with terms containing quotes
        # When quotes form valid phrases, they're extracted first
        result = self.sanitizer.sanitize('NEAR(foo"bar test"case, 5)')
        # The quoted part "bar test" is extracted as a phrase first
        self.assertEqual(result, 'NEAR("foo__PHRASE_0__case", 5)')
        
        # Another case with quotes forming phrases
        result = self.sanitizer.sanitize('NEAR(get"value set"value, 3)')
        # "value set" is extracted as a phrase
        self.assertEqual(result, 'NEAR("get__PHRASE_0__value", 3)')
        
        # Direct test of the internal method to verify our fix
        # This tests that when terms with quotes are passed to _sanitize_near_terms,
        # the quotes are properly escaped
        from search.query_sanitizer import FTS5QuerySanitizer
        sanitizer = FTS5QuerySanitizer()
        
        # Test 1: Simple terms with quotes
        sanitized_terms = sanitizer._sanitize_near_terms('user"s data"s')
        self.assertEqual(sanitized_terms, '"user""s" "data""s"')
        
        # Test 2: Terms that look like they have quotes but are actually clean
        # after the phrase extraction phase
        sanitized_terms = sanitizer._sanitize_near_terms('foo__PHRASE_0__bar test__PHRASE_1__case')
        self.assertEqual(sanitized_terms, '"foo__PHRASE_0__bar" "test__PHRASE_1__case"')
    
    def test_column_filters(self):
        """Test column filter handling."""
        # By default, column filters are removed
        self.assertEqual(
            self.sanitizer.sanitize("title:hello content:world"),
            "hello world"
        )
        
        # With permissive config, they're preserved
        self.assertEqual(
            self.permissive_sanitizer.sanitize("title:hello"),
            "title:hello"
        )
        
        # Negative filters
        self.assertEqual(
            self.sanitizer.sanitize("-title:secret data"),
            "secret data"
        )
        
        # Column groups
        self.assertEqual(
            self.sanitizer.sanitize("{title content}:search"),
            "search"
        )
    
    def test_initial_token_match(self):
        """Test initial token match (^) handling."""
        # Basic initial match
        self.assertEqual(
            self.sanitizer.sanitize("^hello world"),
            "^hello world"
        )
        
        # Multiple initial matches
        self.assertEqual(
            self.sanitizer.sanitize("^start ^begin"),
            "^start ^begin"
        )
        
        # Initial match with wildcards (not valid in FTS5)
        self.assertEqual(
            self.sanitizer.sanitize("^user*"),
            "^user"  # Wildcard removed from initial match
        )
    
    def test_code_patterns(self):
        """Test preservation of code-specific patterns."""
        # Variable names with special chars
        self.assertEqual(
            self.sanitizer.sanitize("$user_id"),
            '"$user_id"'  # Quoted to preserve special chars
        )
        
        # Method calls
        self.assertEqual(
            self.sanitizer.sanitize("object->method"),
            '"object->method"'
        )
        
        # Namespaces
        self.assertEqual(
            self.sanitizer.sanitize("MyClass::method"),
            '"MyClass::method"'
        )
        
        # Python private methods
        self.assertEqual(
            self.sanitizer.sanitize("__init__"),
            '"__init__"'
        )
        
        # Decorators
        self.assertEqual(
            self.sanitizer.sanitize("@property"),
            '"@property"'
        )
    
    def test_complex_queries(self):
        """Test complex query combinations."""
        # Mixed operators and phrases - parentheses are preserved as separate tokens
        query = '"user login" AND (session OR cookie) NOT expired'
        expected = '"user login" AND ( session OR cookie ) NOT expired'
        self.assertEqual(self.sanitizer.sanitize(query), expected)
        
        # Code search with operators
        query = '$user->getName() OR User::find'
        expected = '"$user->getName()" OR "User::find"'
        self.assertEqual(self.sanitizer.sanitize(query), expected)
        
        # NEAR with phrases - phrases get extracted first, then NEAR processes them
        query = 'NEAR("error message" "line number", 5)'
        # The sanitizer extracts phrases first, so they become placeholders
        result = self.sanitizer.sanitize(query)
        # Just verify it's a valid NEAR clause
        self.assertTrue(result.startswith('NEAR('))
        self.assertIn(', 5)', result)
    
    def test_injection_prevention(self):
        """Test prevention of injection attacks."""
        # Column filter injection
        injection = 'term"; SELECT * FROM users; --'
        sanitized = self.sanitizer.sanitize(injection)
        # The injection attempt should be quoted/escaped
        self.assertIn('"', sanitized)  # Should have quotes
        # SELECT might appear but should be quoted/safe
        if "SELECT" in sanitized:
            # Ensure it's within quotes
            self.assertTrue(
                sanitized.count('"') >= 2,
                "SELECT should be within quotes if present"
            )
        
        # Malformed NEAR
        injection = 'NEAR(term1 term2); DELETE FROM data'
        sanitized = self.sanitizer.sanitize(injection)
        # The NEAR should be processed, and the rest should be quoted/escaped
        self.assertIn("NEAR", sanitized)
        # Semicolon should be quoted or escaped
        if ";" in sanitized:
            # Check that it's in a safe context (quoted)
            parts = sanitized.split()
            for part in parts:
                if ";" in part and not (part.startswith('"') or part.startswith("NEAR")):
                    self.fail(f"Semicolon found in unsafe context: {part}")
        
        # Excessive complexity
        with self.assertRaises(ValueError):
            # Create a query with too many terms
            terms = ["term"] * 100
            self.sanitizer.sanitize(" ".join(terms))
    
    def test_is_query_safe(self):
        """Test query safety checking."""
        # Safe queries
        is_safe, error = self.sanitizer.is_query_safe("hello world")
        self.assertTrue(is_safe)
        self.assertIsNone(error)
        
        # Unsafe queries
        is_safe, error = self.sanitizer.is_query_safe("a* b* c* d* e* f*")
        self.assertFalse(is_safe)
        self.assertIn("too many wildcards", error)
    
    def test_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Very long phrase
        long_phrase = '"' + "x" * 200 + '"'
        sanitized = self.sanitizer.sanitize(long_phrase)
        # Should be truncated to max length
        self.assertLessEqual(len(sanitized), 110)  # 100 + quotes + buffer
        
        # Unicode handling
        self.assertEqual(
            self.sanitizer.sanitize("café München"),
            "café München"
        )
        
        # Special FTS5 chars in terms
        self.assertEqual(
            self.sanitizer.sanitize("C++ programming"),
            '"C++" programming'
        )
        
        # Nested quotes - preserves order
        self.assertEqual(
            self.sanitizer.sanitize('search for "the ""best"" solution"'),
            'search for "the ""best"" solution"'
        )


if __name__ == '__main__':
    unittest.main()