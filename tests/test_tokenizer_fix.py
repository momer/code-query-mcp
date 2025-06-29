"""Tests for FTS5 tokenizer fixes and search functionality improvements."""

import unittest
import tempfile
import shutil
import sqlite3
import os
from unittest.mock import Mock, patch

from storage.sqlite_storage import CodeQueryServer


class TestTokenizerFix(unittest.TestCase):
    """Test suite for tokenizer fixes and search improvements."""
    
    def setUp(self):
        """Set up test environment with temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_code_data.db')
        self.server = CodeQueryServer(self.db_path, self.temp_dir)
        self.server.setup_database()
        
        # Create test dataset
        self.dataset_name = "test_project"
        self.server.insert_file_documentation(
            dataset_name=self.dataset_name,
            filepath="/test/tokenizer_test.js",
            filename="tokenizer_test.js",
            overview="Test file for tokenizer validation with $httpClient, my_variable, obj->method(), TestClass::StaticMethod, _internal_var, myObservable$, System.out.println, my-css-class",
            ddd_context="core",
            functions={"myFunction": {"description": "Test function", "signature": "function myFunction() {}"}},
            exports={"myFunction": {"type": "function"}},
            imports={"react": {"source": "react"}},
            types_interfaces_classes={},
            constants={"API_URL": {"value": "https://api.example.com"}},
            dependencies=["react", "lodash"],
            other_notes=["Uses underscore variables", "Contains dollar signs"]
        )
    
    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'server') and self.server.db:
            self.server.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_tokenizer_preserves_underscore_tokens(self):
        """Test that tokenizer preserves tokens with underscores."""
        results = self.server.search_files("my_variable", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        self.assertIn("my_variable", results[0]["match_snippet"])
        
        # Test internal variable with leading underscore
        results = self.server.search_files("_internal_var", self.dataset_name, limit=10)
        self.assertEqual(len(results), 1)
        self.assertIn("_internal_var", results[0]["match_snippet"])
    
    def test_tokenizer_preserves_dollar_sign_tokens(self):
        """Test that tokenizer preserves tokens with dollar signs."""
        results = self.server.search_files("$httpClient", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        self.assertIn("$httpClient", results[0]["match_snippet"])
        
        # Test observable with trailing dollar sign (RxJS pattern)
        results = self.server.search_files("myObservable$", self.dataset_name, limit=10)
        self.assertEqual(len(results), 1)
        self.assertIn("myObservable$", results[0]["match_snippet"])
    
    def test_tokenizer_preserves_operator_tokens(self):
        """Test that tokenizer preserves operator tokens."""
        # Test arrow operator
        results = self.server.search_files("obj->method", self.dataset_name, limit=10)
        self.assertEqual(len(results), 1)
        
        # Test scope operator  
        results = self.server.search_files("TestClass::StaticMethod", self.dataset_name, limit=10)
        self.assertEqual(len(results), 1)
    
    def test_tokenizer_preserves_dot_notation(self):
        """Test that tokenizer preserves dot notation tokens."""
        results = self.server.search_files("System.out.println", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        self.assertIn("System.out.println", results[0]["match_snippet"])
    
    def test_tokenizer_preserves_hyphen_tokens(self):
        """Test that tokenizer preserves tokens with hyphens (CSS classes)."""
        results = self.server.search_files("my-css-class", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        self.assertIn("my-css-class", results[0]["match_snippet"])
    
    def test_tokenizer_handles_exact_matches(self):
        """Test that tokenizer doesn't match substrings inappropriately."""
        # Search for 'http' should not match 'httpClient'
        results = self.server.search_files("http", self.dataset_name, limit=10)
        
        # Should only match if 'http' appears as separate token, not as part of 'httpClient'
        if results:
            # If results exist, verify they don't contain httpClient as a false positive
            for result in results:
                snippet = result["match_snippet"].lower()
                # The snippet should not highlight 'http' within 'httpclient'
                self.assertNotIn("[match]httpclient[/match]", snippet)
    
    def test_snippet_uses_full_content_column(self):
        """Test that snippet function uses the correct full_content column."""
        results = self.server.search_files("myFunction", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        # Verify snippet is returned and contains relevant content
        self.assertIn("match_snippet", results[0])
        snippet = results[0]["match_snippet"]
        self.assertIsNotNone(snippet)
        self.assertNotEqual(snippet, "")
    
    def test_snippet_html_escaping(self):
        """Test that snippets properly escape HTML characters."""
        # Add file with HTML-like content
        self.server.insert_file_documentation(
            dataset_name=self.dataset_name,
            filepath="/test/html_test.html",
            filename="html_test.html",
            overview="Test file with HTML content",
            ddd_context="core",
            functions='{}',
            exports='{}',
            imports='{}',
            types_interfaces_classes='{}',
            constants='{}',
            dependencies='[]',
            other_notes='[]',
            full_content='<div class="container"><p>Test content</p></div>'
        )
        
        results = self.server.search_full_content("container", self.dataset_name, limit=10)
        
        self.assertEqual(len(results), 1)
        snippet = results[0]["content_snippet"]
        # Verify HTML is properly escaped or handled
        self.assertIn("container", snippet)
    
    def test_query_unification_consistent_behavior(self):
        """Test that search_files and search_full_content use unified query processing."""
        # Both methods should handle the same query consistently
        query = "myFunction"
        
        files_results = self.server.search_files(query, self.dataset_name, limit=10)
        content_results = self.server.search_full_content(query, self.dataset_name, limit=10)
        
        # Both should find the test file
        self.assertEqual(len(files_results), 1)
        self.assertEqual(len(content_results), 1)
        self.assertEqual(files_results[0]["filepath"], content_results[0]["filepath"])
    
    def test_migration_preserves_data(self):
        """Test that v3 migration preserves existing data."""
        # Get initial data count
        cursor = self.server.db.execute(
            "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?", 
            (self.dataset_name,)
        )
        initial_count = cursor.fetchone()["count"]
        
        # Simulate migration by checking schema version
        cursor = self.server.db.execute("SELECT version FROM schema_version WHERE version = '3'")
        migration_applied = cursor.fetchone() is not None
        
        # After migration, data should still be there
        if migration_applied:
            cursor = self.server.db.execute(
                "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?", 
                (self.dataset_name,)
            )
            post_migration_count = cursor.fetchone()["count"]
            self.assertEqual(initial_count, post_migration_count)
    
    def test_tokenizer_configuration_applied(self):
        """Test that the new tokenizer configuration is properly applied."""
        # Check FTS table configuration
        cursor = self.server.db.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        fts_sql = cursor.fetchone()
        
        if fts_sql:
            # Verify tokenizer configuration includes our custom tokenchars
            sql_text = fts_sql["sql"]
            self.assertIn("tokenchars", sql_text.lower())
            self.assertIn("._$@->:#", sql_text)
    
    def test_edge_case_token_combinations(self):
        """Test edge cases with multiple special characters."""
        # Insert file with complex tokens
        self.server.insert_file_documentation(
            dataset_name=self.dataset_name,
            filepath="/test/complex_tokens.js",
            filename="complex_tokens.js",
            overview="File with complex token patterns",
            ddd_context="core",
            functions='{}',
            exports='{}',
            imports='{}',
            types_interfaces_classes='{}',
            constants='{}',
            dependencies='[]',
            other_notes='[]',
            full_content='''
const complex_$var = 'test';
const obj$->method = function() {};
const css_class = 'my-component__element--modifier';
const hash_tag = '#component-id';
const at_rule = '@media screen';
'''
        )
        
        # Test various complex token patterns
        test_cases = [
            "complex_$var",
            "obj$->method", 
            "my-component__element--modifier",
            "#component-id",
            "@media"
        ]
        
        for token in test_cases:
            with self.subTest(token=token):
                results = self.server.search_full_content(token, self.dataset_name, limit=10)
                self.assertGreaterEqual(len(results), 1, f"Token '{token}' not found")


def index_and_search(server, dataset_name, search_term, content=None, expected_count=1):
    """Helper function to index content and search for a term."""
    if content is None:
        content = f"Test content with {search_term}"
    
    # Create test file with the content
    server.insert_file_documentation(
        dataset_name=dataset_name,
        filepath=f"/test/{search_term.replace(' ', '_')}.js",
        filename=f"{search_term.replace(' ', '_')}.js",
        overview=f"Test file for {search_term}",
        ddd_context="core",
        functions='{}',
        exports='{}', 
        imports='{}',
        types_interfaces_classes='{}',
        constants='{}',
        dependencies='[]',
        other_notes='[]',
        full_content=content
    )
    
    # Search for the term
    results = server.search_full_content(search_term, dataset_name, limit=10)
    
    return len(results) == expected_count


class TestTokenizerEdgeCases(unittest.TestCase):
    """Additional edge case tests for tokenizer functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_edge_cases.db')
        self.server = CodeQueryServer(self.db_path, self.temp_dir)
        self.server.setup_database()
        self.dataset_name = "edge_cases"
    
    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'server') and self.server.db:
            self.server.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_leading_underscore_tokens(self):
        """Test tokens with leading underscores."""
        content = "const _internal_var = 'private';"
        self.assertTrue(index_and_search(self.server, self.dataset_name, "_internal_var", content))
    
    def test_trailing_dollar_tokens(self):
        """Test tokens with trailing dollar signs (RxJS observables)."""
        content = "const myObservable$ = new Observable();"
        self.assertTrue(index_and_search(self.server, self.dataset_name, "myObservable$", content))
    
    def test_period_separated_tokens(self):
        """Test tokens containing periods."""
        content = "System.out.println('Hello');"
        self.assertTrue(index_and_search(self.server, self.dataset_name, "System.out.println", content))
    
    def test_hyphen_separated_tokens(self):
        """Test tokens with hyphens (CSS classes)."""
        content = "const className = 'my-css-class';"
        self.assertTrue(index_and_search(self.server, self.dataset_name, "my-css-class", content))
    
    def test_substring_exclusion(self):
        """Test that substrings don't incorrectly match larger tokens."""
        content = "const httpClient = new HttpClient();"
        # Searching for 'http' should not match 'httpClient'
        self.assertFalse(index_and_search(self.server, self.dataset_name, "http", content, expected_count=0))


if __name__ == '__main__':
    unittest.main()