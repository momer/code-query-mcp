"""Tests for the SearchService implementation."""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any

from search.search_service import (
    SearchService, SearchConfig, SearchMode,
    SearchServiceInterface
)
from search.query_builder import FTS5QueryBuilder
from search.query_sanitizer import FTS5QuerySanitizer, SanitizationConfig
from search.models import FileMetadata, SearchResult


class TestSearchService(unittest.TestCase):
    """Test the SearchService implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock storage backend
        self.mock_storage = Mock()
        
        # Mock query builder
        self.mock_query_builder = Mock(spec=FTS5QueryBuilder)
        
        # Mock query sanitizer
        self.mock_sanitizer = Mock(spec=FTS5QuerySanitizer)
        
        # Create service with mocks
        self.service = SearchService(
            storage_backend=self.mock_storage,
            query_builder=self.mock_query_builder,
            query_sanitizer=self.mock_sanitizer
        )
        
        # Sample metadata results
        self.sample_metadata = [
            FileMetadata(
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
            ),
            FileMetadata(
                file_id=2,
                file_path="/project/src/user.py",
                file_name="user.py",
                file_extension="py",
                file_size=2048,
                last_modified="2024-01-02",
                content_hash="def456",
                dataset_id="test_dataset",
                overview="User management",
                language="python",
                functions=["create_user", "delete_user"],
                exports=["UserService"]
            )
        ]
        
        # Sample search results
        self.sample_search_results = [
            SearchResult(
                file_path="/project/src/auth.py",
                dataset_id="test_dataset",
                match_content="def login(username, password):",
                match_type="content",
                relevance_score=0.95,
                snippet="...def login(username, password):\n    # Authenticate user...",
                metadata=self.sample_metadata[0]
            ),
            SearchResult(
                file_path="/project/src/user.py",
                dataset_id="test_dataset",
                match_content="class UserService:",
                match_type="content",
                relevance_score=0.85,
                snippet="...class UserService:\n    def create_user(self, data):...",
                metadata=self.sample_metadata[1]
            )
        ]
    
    def test_init_with_defaults(self):
        """Test initialization with default dependencies."""
        service = SearchService(self.mock_storage)
        
        # Should create default instances
        self.assertIsInstance(service.query_builder, FTS5QueryBuilder)
        self.assertIsInstance(service.query_sanitizer, FTS5QuerySanitizer)
        self.assertIsInstance(service.default_config, SearchConfig)
    
    def test_init_with_custom_dependencies(self):
        """Test initialization with custom dependencies."""
        custom_config = SearchConfig(max_results=100)
        
        service = SearchService(
            storage_backend=self.mock_storage,
            query_builder=self.mock_query_builder,
            query_sanitizer=self.mock_sanitizer,
            default_config=custom_config
        )
        
        self.assertEqual(service.query_builder, self.mock_query_builder)
        self.assertEqual(service.query_sanitizer, self.mock_sanitizer)
        self.assertEqual(service.default_config.max_results, 100)
    
    def test_search_metadata_with_sanitization(self):
        """Test metadata search with query sanitization enabled."""
        # Setup - mock the sanitizer to be used
        with patch.object(self.service, 'query_sanitizer') as mock_sanitizer:
            mock_sanitizer.sanitize.return_value = "sanitized query"
            self.mock_query_builder.build_query.return_value = "fts5_query"
            self.mock_storage.search_files.return_value = self.sample_metadata
            
            # Execute
            results = self.service.search_metadata("user login", "test_dataset")
            
            # Verify sanitization was called
            mock_sanitizer.sanitize.assert_called_once_with("user login")
            
            # Verify query building
            self.mock_query_builder.build_query.assert_called_once_with("sanitized query")
            
            # Verify storage call
            self.mock_storage.search_files.assert_called_once_with(
                query="fts5_query",
                dataset_id="test_dataset",
                limit=50
            )
            
            # Verify results
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].file_path, "/project/src/auth.py")
    
    def test_search_metadata_sanitization_failure(self):
        """Test metadata search when sanitization fails."""
        # Setup - sanitizer raises ValueError
        with patch.object(self.service, 'query_sanitizer') as mock_sanitizer:
            mock_sanitizer.sanitize.side_effect = ValueError("Invalid query")
            
            # Execute
            results = self.service.search_metadata("bad; query--", "test_dataset")
            
            # Should return empty results
            self.assertEqual(results, [])
            
            # Storage should not be called
            self.mock_storage.search_files.assert_not_called()
    
    def test_search_metadata_with_fallback(self):
        """Test metadata search with fallback variants."""
        # Setup
        config = SearchConfig(enable_fallback=True, enable_query_sanitization=False)
        self.mock_query_builder.get_query_variants.return_value = [
            "variant1", "variant2", "variant3"
        ]
        
        # First variant returns no results, second returns some
        self.mock_storage.search_files.side_effect = [
            [],  # variant1
            self.sample_metadata[:1],  # variant2
        ]
        
        # Execute
        results = self.service.search_metadata("user login", "test_dataset", config)
        
        # Verify fallback was used
        self.mock_query_builder.get_query_variants.assert_called_once_with("user login")
        
        # Verify multiple storage calls
        self.assertEqual(self.mock_storage.search_files.call_count, 2)
        
        # Verify results from second variant
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file_path, "/project/src/auth.py")
    
    def test_search_metadata_code_aware(self):
        """Test metadata search with code-aware query building."""
        # Setup
        config = SearchConfig(
            enable_code_aware=True,
            enable_fallback=False,
            enable_query_sanitization=False
        )
        # When not using fallback, build_code_aware_query returns a string wrapped in a list internally
        self.mock_query_builder.build_code_aware_query.return_value = "code_aware_query"
        self.mock_storage.search_files.return_value = self.sample_metadata
        
        # Execute
        results = self.service.search_metadata("$user->login()", "test_dataset", config)
        
        # Verify code-aware query was used
        self.mock_query_builder.build_code_aware_query.assert_called_once_with("$user->login()")
        
        # Verify storage call
        self.mock_storage.search_files.assert_called_once_with(
            query="code_aware_query",
            dataset_id="test_dataset",
            limit=50
        )
    
    def test_search_content_with_relevance_filter(self):
        """Test content search with relevance score filtering."""
        # Setup
        config = SearchConfig(
            enable_relevance_scoring=True,
            min_relevance_score=0.9,
            enable_query_sanitization=False
        )
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_full_content.return_value = self.sample_search_results
        
        # Execute
        results = self.service.search_content("login", "test_dataset", config)
        
        # Verify only high-relevance results returned
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].relevance_score, 0.95)
    
    def test_search_content_with_deduplication(self):
        """Test content search with deduplication."""
        # Setup
        config = SearchConfig(
            deduplicate_results=True,
            enable_query_sanitization=False
        )
        
        # Create duplicate results
        duplicate_results = [
            self.sample_search_results[0],
            SearchResult(
                file_path="/project/src/auth.py",  # Same file
                dataset_id="test_dataset",
                match_content="def login(username, password):",  # Same content
                match_type="content",
                relevance_score=0.90,
                snippet="duplicate",
                metadata=self.sample_metadata[0]
            ),
            self.sample_search_results[1]
        ]
        
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_full_content.return_value = duplicate_results
        
        # Execute
        results = self.service.search_content("login", "test_dataset", config)
        
        # Verify deduplication
        self.assertEqual(len(results), 2)  # One duplicate removed
        self.assertEqual(results[0].file_path, "/project/src/auth.py")
        self.assertEqual(results[1].file_path, "/project/src/user.py")
    
    def test_search_unified_mode(self):
        """Test unified search mode combining metadata and content."""
        # Setup
        config = SearchConfig(
            search_mode=SearchMode.UNIFIED,
            enable_query_sanitization=False
        )
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_files.return_value = self.sample_metadata
        self.mock_storage.search_full_content.return_value = self.sample_search_results[:1]
        
        # Execute
        results = self.service.search("login", "test_dataset", config)
        
        # Verify both searches were called
        self.mock_storage.search_files.assert_called()
        self.mock_storage.search_full_content.assert_called()
        
        # Results should be combined with content results first
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].match_type, "content")  # Content result first
        self.assertEqual(results[1].match_type, "metadata")  # Then metadata-only
    
    def test_search_metadata_only_mode(self):
        """Test search with metadata-only mode."""
        config = SearchConfig(
            search_mode=SearchMode.METADATA_ONLY,
            enable_query_sanitization=False
        )
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_files.return_value = self.sample_metadata
        
        # Execute
        results = self.service.search("login", "test_dataset", config)
        
        # Verify only metadata search was called
        self.mock_storage.search_files.assert_called()
        self.mock_storage.search_full_content.assert_not_called()
        
        # Results should be SearchResult objects converted from metadata
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].match_type, "metadata")
    
    def test_search_content_only_mode(self):
        """Test search with content-only mode."""
        config = SearchConfig(
            search_mode=SearchMode.CONTENT_ONLY,
            enable_query_sanitization=False
        )
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_full_content.return_value = self.sample_search_results
        
        # Execute
        results = self.service.search("login", "test_dataset", config)
        
        # Verify only content search was called
        self.mock_storage.search_full_content.assert_called()
        self.mock_storage.search_files.assert_not_called()
        
        # Results should be content results
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].match_type, "content")
    
    def test_metadata_to_search_result_conversion(self):
        """Test conversion of FileMetadata to SearchResult."""
        metadata = self.sample_metadata[0]
        
        # Call private method
        result = self.service._metadata_to_search_result(metadata)
        
        # Verify conversion
        self.assertEqual(result.file_path, metadata.file_path)
        self.assertEqual(result.dataset_id, metadata.dataset_id)
        self.assertEqual(result.match_type, "metadata")
        self.assertEqual(result.relevance_score, 0.5)  # Default score
        self.assertEqual(result.match_content, metadata.overview)
        self.assertEqual(result.metadata, metadata)
    
    def test_unified_search_deduplication(self):
        """Test unified search properly deduplicates across metadata and content."""
        # Setup - same file in both results
        config = SearchConfig(
            search_mode=SearchMode.UNIFIED,
            deduplicate_results=True,
            enable_query_sanitization=False
        )
        self.mock_query_builder.build_query.return_value = "fts5_query"
        self.mock_storage.search_files.return_value = self.sample_metadata
        self.mock_storage.search_full_content.return_value = self.sample_search_results
        
        # Execute
        results = self.service.search("login", "test_dataset", config)
        
        # Verify no duplicate file paths
        file_paths = [r.file_path for r in results]
        self.assertEqual(len(file_paths), len(set(file_paths)))
        
        # Content results should take precedence
        auth_results = [r for r in results if r.file_path == "/project/src/auth.py"]
        self.assertEqual(len(auth_results), 1)
        self.assertEqual(auth_results[0].match_type, "content")
    
    def test_search_with_custom_sanitization_config(self):
        """Test search with custom sanitization configuration."""
        # Setup
        sanitization_config = SanitizationConfig(
            allow_column_filters=True,
            max_wildcards=10
        )
        config = SearchConfig(
            enable_query_sanitization=True,
            sanitization_config=sanitization_config
        )
        
        # Create a new sanitizer mock that will be created with config
        with patch('search.search_service.FTS5QuerySanitizer') as MockSanitizer:
            mock_sanitizer_instance = Mock()
            mock_sanitizer_instance.sanitize.return_value = "sanitized"
            MockSanitizer.return_value = mock_sanitizer_instance
            
            self.mock_query_builder.build_query.return_value = "fts5_query"
            self.mock_storage.search_files.return_value = []
            
            # Execute
            self.service.search_metadata("title:test*", "test_dataset", config)
            
            # Verify sanitizer was created with custom config
            MockSanitizer.assert_called_once_with(sanitization_config)
            mock_sanitizer_instance.sanitize.assert_called_once_with("title:test*")
    
    def test_exception_handling_in_fallback(self):
        """Test that exceptions during search don't break fallback."""
        # Setup
        config = SearchConfig(enable_fallback=True, enable_query_sanitization=False)
        self.mock_query_builder.get_query_variants.return_value = [
            "variant1", "variant2", "variant3"
        ]
        
        # First variant throws exception, second succeeds
        self.mock_storage.search_files.side_effect = [
            Exception("Database error"),
            self.sample_metadata[:1]
        ]
        
        # Execute - should not raise
        results = self.service.search_metadata("test", "test_dataset", config)
        
        # Should have results from second variant
        self.assertEqual(len(results), 1)
        self.assertEqual(self.mock_storage.search_files.call_count, 2)


class TestSearchServiceInterface(unittest.TestCase):
    """Test the SearchServiceInterface protocol."""
    
    def test_interface_compliance(self):
        """Test that SearchService implements SearchServiceInterface."""
        # This will fail at runtime if interface is not satisfied
        service: SearchServiceInterface = SearchService(Mock())
        
        # Verify required methods exist
        self.assertTrue(hasattr(service, 'search'))
        self.assertTrue(hasattr(service, 'search_metadata'))
        self.assertTrue(hasattr(service, 'search_content'))


if __name__ == '__main__':
    unittest.main()