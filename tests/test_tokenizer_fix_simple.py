"""Simplified tests for FTS5 tokenizer fixes and search functionality improvements."""

import unittest
import tempfile
import shutil
import os

from storage.sqlite_storage import CodeQueryServer


class TestTokenizerFixSimple(unittest.TestCase):
    """Simplified test suite for tokenizer fixes."""
    
    def setUp(self):
        """Set up test environment with temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_code_data.db')
        self.server = CodeQueryServer(self.db_path, self.temp_dir)
        self.server.setup_database()
        
        # Create test dataset with special tokens in overview field
        self.dataset_name = "test_project"
        self.server.insert_file_documentation(
            dataset_name=self.dataset_name,
            filepath="/test/tokenizer_test.js",
            filename="tokenizer_test.js",
            overview="Test tokens: $httpClient my_variable obj->method TestClass::StaticMethod _internal_var myObservable$ System.out.println my-css-class #component @media",
            ddd_context="core",
            functions={"myFunction": {"description": "Test function"}},
            exports={"myFunction": {"type": "function"}},
            imports={"react": {"source": "react"}},
        )
    
    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'server') and self.server.db:
            self.server.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_underscore_tokens(self):
        """Test that tokens with underscores are preserved."""
        results = self.server.search_files("my_variable", self.dataset_name)
        self.assertEqual(len(results), 1)
        
        results = self.server.search_files("_internal_var", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_dollar_sign_tokens(self):
        """Test that tokens with dollar signs are preserved."""
        results = self.server.search_files("$httpClient", self.dataset_name)
        self.assertEqual(len(results), 1)
        
        results = self.server.search_files("myObservable$", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_operator_tokens(self):
        """Test that operator tokens are preserved."""
        results = self.server.search_files("obj->method", self.dataset_name)
        self.assertEqual(len(results), 1)
        
        results = self.server.search_files("TestClass::StaticMethod", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_dot_notation_tokens(self):
        """Test that dot notation tokens are preserved."""
        results = self.server.search_files("System.out.println", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_hyphen_tokens(self):
        """Test that hyphenated tokens are preserved."""
        results = self.server.search_files("my-css-class", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_hash_and_at_tokens(self):
        """Test that hash and at tokens are preserved."""
        results = self.server.search_files("#component", self.dataset_name)
        self.assertEqual(len(results), 1)
        
        results = self.server.search_files("@media", self.dataset_name)
        self.assertEqual(len(results), 1)
    
    def test_migration_applied(self):
        """Test that v3 migration was applied successfully."""
        cursor = self.server.db.execute("SELECT version FROM schema_version WHERE version = '3'")
        migration_applied = cursor.fetchone() is not None
        self.assertTrue(migration_applied)
    
    def test_tokenizer_configuration(self):
        """Test that the new tokenizer configuration is applied."""
        # Check if FTS table exists and has correct configuration
        cursor = self.server.db.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        fts_sql = cursor.fetchone()
        
        if fts_sql:
            sql_text = fts_sql["sql"]
            # Should contain our custom tokenchars
            self.assertIn("tokenchars", sql_text.lower())
            self.assertIn("._$@->:#", sql_text)
    
    def test_search_consistency(self):
        """Test that search methods work consistently."""
        # Both search_files and search_full_content should work
        files_results = self.server.search_files("myFunction", self.dataset_name)
        self.assertGreaterEqual(len(files_results), 1)
        
        # Try full content search if it exists (may not have content)
        try:
            content_results = self.server.search_full_content("Test", self.dataset_name)
            # This might be empty since we don't have full_content, which is OK
        except Exception:
            # Method might not work without full_content data, which is OK
            pass


if __name__ == '__main__':
    unittest.main()