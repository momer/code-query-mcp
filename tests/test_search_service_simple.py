"""Simplified tests for the SearchService implementation."""

import unittest
from unittest.mock import Mock, patch
from typing import List

from search.search_service import (
    SearchService, SearchConfig, SearchMode
)
from search.models import FileMetadata, SearchResult


class TestSearchServiceSimple(unittest.TestCase):
    """Simplified tests for SearchService focusing on core functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock storage backend
        self.mock_storage = Mock()
        
        # Create service with real query builder and sanitizer
        self.service = SearchService(storage_backend=self.mock_storage)
        
        # Sample file metadata
        self.sample_metadata = FileMetadata(
            file_id=1,
            file_path="/project/src/auth.py",
            file_name="auth.py",
            file_extension="py",
            file_size=1024,
            last_modified="2024-01-01",
            content_hash="abc123",
            dataset_id="test_dataset",
            overview="Authentication module",
            language="python",
            functions=["login", "logout"],
            exports=["AuthManager"]
        )
    
    def test_search_metadata_basic(self):
        """Test basic metadata search without sanitization."""
        # Setup
        config = SearchConfig(
            enable_query_sanitization=False,
            enable_fallback=False,
            enable_code_aware=False
        )
        
        # Mock the storage to return a list-like result
        self.mock_storage.search_files.return_value = [self.sample_metadata]
        
        # Execute
        results = self.service.search_metadata("login", "test_dataset", config)
        
        # Verify storage was called
        self.mock_storage.search_files.assert_called_once()
        call_args = self.mock_storage.search_files.call_args
        self.assertEqual(call_args[1]['dataset_id'], "test_dataset")
        self.assertIn('query', call_args[1])
        
        # Verify results
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file_path, "/project/src/auth.py")
    
    def test_search_metadata_with_sanitization(self):
        """Test metadata search with sanitization enabled."""
        # Setup - use config without fallback
        config = SearchConfig(
            enable_query_sanitization=True,
            enable_fallback=False
        )
        self.mock_storage.search_files.return_value = [self.sample_metadata]
        
        # Execute with a query that needs sanitization
        results = self.service.search_metadata("login AND logout", "test_dataset", config)
        
        # Verify storage was called exactly once
        self.mock_storage.search_files.assert_called_once()
        
        # The query should have been sanitized and built
        call_args = self.mock_storage.search_files.call_args
        query = call_args[1]['query']
        # Should contain proper FTS5 syntax
        self.assertIn('AND', query)  # Operators preserved
        
        # Verify results
        self.assertEqual(len(results), 1)
    
    def test_search_metadata_injection_prevention(self):
        """Test that injection attempts are sanitized."""
        # Setup with no fallback
        config = SearchConfig(
            enable_query_sanitization=True,
            enable_fallback=False
        )
        self.mock_storage.search_files.return_value = []
        
        # Execute with injection attempt
        results = self.service.search_metadata(
            'login"; SELECT * FROM users; --', 
            "test_dataset",
            config
        )
        
        # Query should be sanitized - check that it doesn't contain raw SQL
        call_args = self.mock_storage.search_files.call_args
        query = call_args[1]['query']
        self.assertNotIn('SELECT * FROM users', query)
        
        # Should still execute (not fail)
        self.mock_storage.search_files.assert_called_once()
    
    def test_search_content_basic(self):
        """Test basic content search."""
        # Setup
        config = SearchConfig(
            enable_query_sanitization=False,
            enable_fallback=False
        )
        
        # Create a search result
        search_result = SearchResult(
            file_path="/project/src/auth.py",
            dataset_id="test_dataset",
            match_content="def login(username, password):",
            match_type="content",
            relevance_score=0.95,
            snippet="...def login(username, password):\n    # Auth logic...",
            metadata=self.sample_metadata
        )
        
        self.mock_storage.search_full_content.return_value = [search_result]
        
        # Execute
        results = self.service.search_content("login", "test_dataset", config)
        
        # Verify storage was called
        self.mock_storage.search_full_content.assert_called_once()
        
        # Verify results
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file_path, "/project/src/auth.py")
        self.assertEqual(results[0].match_type, "content")
    
    def test_search_unified_mode(self):
        """Test unified search combining metadata and content."""
        # Setup
        config = SearchConfig(
            search_mode=SearchMode.UNIFIED,
            enable_query_sanitization=False,
            enable_fallback=False
        )
        
        # Create different results for metadata and content
        metadata_result = self.sample_metadata
        
        content_result = SearchResult(
            file_path="/project/src/user.py",
            dataset_id="test_dataset",
            match_content="class UserService:",
            match_type="content",
            relevance_score=0.85,
            snippet="...class UserService:...",
            metadata=None
        )
        
        self.mock_storage.search_files.return_value = [metadata_result]
        self.mock_storage.search_full_content.return_value = [content_result]
        
        # Execute unified search
        results = self.service.search("user", "test_dataset", config)
        
        # Both searches should be called
        self.mock_storage.search_files.assert_called()
        self.mock_storage.search_full_content.assert_called()
        
        # Should have results from both
        self.assertEqual(len(results), 2)
        # Content results come first
        self.assertEqual(results[0].match_type, "content")
        self.assertEqual(results[1].match_type, "metadata")
    
    def test_search_deduplication(self):
        """Test that unified search deduplicates results."""
        # Setup
        config = SearchConfig(
            search_mode=SearchMode.UNIFIED,
            deduplicate_results=True,
            enable_query_sanitization=False,
            enable_fallback=False
        )
        
        # Same file in both metadata and content results
        metadata_result = self.sample_metadata
        
        content_result = SearchResult(
            file_path="/project/src/auth.py",  # Same file
            dataset_id="test_dataset",
            match_content="def login():",
            match_type="content",
            relevance_score=0.95,
            snippet="...def login():...",
            metadata=self.sample_metadata
        )
        
        self.mock_storage.search_files.return_value = [metadata_result]
        self.mock_storage.search_full_content.return_value = [content_result]
        
        # Execute
        results = self.service.search("login", "test_dataset", config)
        
        # Should only have one result (deduplicated)
        self.assertEqual(len(results), 1)
        # Content result should take precedence
        self.assertEqual(results[0].match_type, "content")
    
    def test_code_pattern_sanitization(self):
        """Test that code patterns with special characters are properly sanitized and quoted."""
        # Setup
        config = SearchConfig(
            enable_code_aware=True,
            enable_query_sanitization=True,
            enable_fallback=False
        )
        
        self.mock_storage.search_files.return_value = [self.sample_metadata]
        
        # Execute with code pattern containing special characters
        results = self.service.search_metadata("$user->login()", "test_dataset", config)
        
        # Verify the query was called
        self.mock_storage.search_files.assert_called_once()
        call_args = self.mock_storage.search_files.call_args
        query = call_args[1]['query']
        
        # The code pattern should be quoted to preserve special characters in FTS5
        self.assertIn('"$user->login()"', query)  # Should quote the entire pattern
        
        # Should return results
        self.assertEqual(len(results), 1)
        
    def test_code_aware_query_building(self):
        """Test that code-aware search uses appropriate query strategies for code patterns."""
        # Setup - test different code patterns
        config = SearchConfig(
            enable_code_aware=True,
            enable_query_sanitization=True,
            enable_fallback=False
        )
        
        test_cases = [
            ("User::find", "Should handle namespace operators"),
            ("__init__", "Should handle Python special methods"),
            ("@property", "Should handle decorators"),
            ("function()", "Should handle function calls")
        ]
        
        for pattern, description in test_cases:
            with self.subTest(pattern=pattern, desc=description):
                self.mock_storage.reset_mock()
                self.mock_storage.search_files.return_value = []
                
                # Execute search
                self.service.search_metadata(pattern, "test_dataset", config)
                
                # Verify query was built
                self.mock_storage.search_files.assert_called_once()
                call_args = self.mock_storage.search_files.call_args
                query = call_args[1]['query']
                
                # Code-aware query builder should handle these patterns
                # Either by quoting them or transforming them appropriately
                self.assertIsNotNone(query)
                self.assertNotEqual(query, '""')  # Should not be empty
    
    def test_search_modes(self):
        """Test different search modes."""
        # Test metadata only mode
        config = SearchConfig(search_mode=SearchMode.METADATA_ONLY)
        self.mock_storage.search_files.return_value = [self.sample_metadata]
        
        results = self.service.search("test", "dataset", config)
        self.mock_storage.search_files.assert_called()
        self.mock_storage.search_full_content.assert_not_called()
        self.assertEqual(results[0].match_type, "metadata")
        
        # Reset mocks
        self.mock_storage.reset_mock()
        
        # Test content only mode
        config = SearchConfig(search_mode=SearchMode.CONTENT_ONLY)
        content_result = SearchResult(
            file_path="/test.py",
            dataset_id="dataset",
            match_content="test",
            match_type="content",
            relevance_score=0.9
        )
        self.mock_storage.search_full_content.return_value = [content_result]
        
        results = self.service.search("test", "dataset", config)
        self.mock_storage.search_full_content.assert_called()
        self.mock_storage.search_files.assert_not_called()
        self.assertEqual(results[0].match_type, "content")


if __name__ == '__main__':
    unittest.main()