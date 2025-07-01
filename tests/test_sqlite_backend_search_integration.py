"""Integration tests for SqliteBackend with SearchService."""

import unittest
import tempfile
import os
from unittest.mock import Mock, patch

from storage.sqlite_backend import SqliteBackend
from storage.models import FileDocumentation, SearchResult
from search.search_service import SearchService, SearchConfig, SearchMode
from search.models import SearchResult as SearchServiceResult


class TestSqliteBackendSearchIntegration(unittest.TestCase):
    """Test SqliteBackend integration with SearchService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary database
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        
        # Create backend (which will create SearchService)
        self.backend = SqliteBackend(self.db_path)
        
        # Create test dataset
        self.backend.create_dataset("test_dataset", "/test/path")
        
        # Insert test documents
        self.test_docs = [
            FileDocumentation(
                filepath="/project/src/auth.py",
                filename="auth.py",
                overview="Authentication module with login and logout",
                dataset="test_dataset",
                ddd_context="Core authentication domain",
                functions={"login": "User login function", "logout": "User logout"},
                exports=["AuthManager", "authenticate"],
                full_content="def login(username, password):\n    # Login implementation\n    pass"
            ),
            FileDocumentation(
                filepath="/project/src/user.py",
                filename="user.py",
                overview="User management module",
                dataset="test_dataset",
                ddd_context="User domain",
                functions={"create_user": "Create new user", "delete_user": "Delete user"},
                exports=["UserService"],
                full_content="class UserService:\n    def create_user(self, data):\n        pass"
            ),
            FileDocumentation(
                filepath="/project/src/database.py",
                filename="database.py",
                overview="Database connection utilities",
                dataset="test_dataset",
                functions={"connect": "Connect to database"},
                exports=["DatabaseConnection"],
                full_content="def connect(host, port):\n    # Connect to database\n    return connection"
            )
        ]
        
        for doc in self.test_docs:
            self.backend.insert_documentation(doc)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.backend.close()
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_search_service_is_initialized(self):
        """Test that SearchService is properly initialized."""
        self.assertIsInstance(self.backend.search_service, SearchService)
        # Verify it uses the backend as storage
        self.assertEqual(self.backend.search_service.storage, self.backend)
    
    def test_metadata_search_uses_search_service(self):
        """Test that metadata search delegates to SearchService."""
        with patch.object(self.backend.search_service, 'search') as mock_search:
            # Mock SearchService response
            mock_search.return_value = [
                SearchServiceResult(
                    file_path="/project/src/auth.py",
                    dataset_id="test_dataset",
                    match_content="Authentication module",
                    match_type="metadata",
                    relevance_score=0.95
                )
            ]
            
            # Call backend search
            results = self.backend.search_metadata("authentication", "test_dataset", limit=10)
            
            # Verify SearchService was called with correct config
            mock_search.assert_called_once()
            call_args = mock_search.call_args
            self.assertEqual(call_args[0][0], "authentication")  # query
            self.assertEqual(call_args[0][1], "test_dataset")   # dataset
            
            config = call_args[0][2]
            self.assertEqual(config.search_mode, SearchMode.METADATA_ONLY)
            self.assertEqual(config.max_results, 10)
            self.assertTrue(config.enable_query_sanitization)
    
    def test_content_search_uses_search_service(self):
        """Test that content search delegates to SearchService."""
        with patch.object(self.backend.search_service, 'search') as mock_search:
            # Mock SearchService response
            mock_search.return_value = [
                SearchServiceResult(
                    file_path="/project/src/auth.py",
                    dataset_id="test_dataset",
                    match_content="def login(username, password):",
                    match_type="content",
                    relevance_score=0.98,
                    snippet="...def login(username, password):..."
                )
            ]
            
            # Call backend search
            results = self.backend.search_content("login", "test_dataset", limit=5)
            
            # Verify SearchService was called with correct config
            mock_search.assert_called_once()
            config = mock_search.call_args[0][2]
            self.assertEqual(config.search_mode, SearchMode.CONTENT_ONLY)
            self.assertEqual(config.max_results, 5)
    
    def test_unified_search_uses_search_service(self):
        """Test that unified search delegates to SearchService."""
        with patch.object(self.backend.search_service, 'search') as mock_search:
            # Mock mixed results
            mock_search.return_value = [
                SearchServiceResult(
                    file_path="/project/src/auth.py",
                    dataset_id="test_dataset",
                    match_content="def login",
                    match_type="content",
                    relevance_score=0.98
                ),
                SearchServiceResult(
                    file_path="/project/src/user.py",
                    dataset_id="test_dataset",
                    match_content="User management",
                    match_type="metadata",
                    relevance_score=0.85
                )
            ]
            
            # Call unified search
            metadata_results, content_results, stats = self.backend.search_unified(
                "user", "test_dataset", limit=20
            )
            
            # Verify SearchService config
            config = mock_search.call_args[0][2]
            self.assertEqual(config.search_mode, SearchMode.UNIFIED)
            self.assertTrue(config.deduplicate_results)
            
            # Verify results are properly separated
            self.assertEqual(len(metadata_results), 1)
            self.assertEqual(len(content_results), 1)
            self.assertEqual(metadata_results[0].filepath, "/project/src/user.py")
            self.assertEqual(content_results[0].filepath, "/project/src/auth.py")
    
    def test_search_service_result_conversion(self):
        """Test conversion between SearchService and storage results."""
        # Create a SearchService result with metadata
        service_result = SearchServiceResult(
            file_path="/test/file.py",
            dataset_id="test_dataset",
            match_content="test match",
            match_type="content",
            relevance_score=0.9,
            snippet="...test snippet...",
            metadata=Mock(
                overview="Test overview",
                ddd_context="Test context",
                file_name="file.py"
            )
        )
        
        # Convert to storage result
        storage_result = self.backend._search_service_result_to_storage_result(service_result)
        
        # Verify conversion
        self.assertEqual(storage_result.filepath, "/test/file.py")
        self.assertEqual(storage_result.filename, "file.py")
        self.assertEqual(storage_result.dataset, "test_dataset")
        self.assertEqual(storage_result.score, 0.9)
        self.assertEqual(storage_result.snippet, "...test snippet...")
        self.assertEqual(storage_result.overview, "Test overview")
        self.assertEqual(storage_result.ddd_context, "Test context")
    
    def test_search_files_method_for_search_service(self):
        """Test search_files method used by SearchService."""
        # This method is called by SearchService for metadata searches
        results = self.backend.search_files(
            "authentication OR login",
            "test_dataset",
            limit=10
        )
        
        # Should return FileMetadata objects
        self.assertGreater(len(results), 0)
        result = results[0]
        self.assertEqual(result.file_path, "/project/src/auth.py")
        self.assertEqual(result.dataset_id, "test_dataset")
        self.assertIn("login", result.functions)
    
    def test_search_full_content_method_for_search_service(self):
        """Test search_full_content method used by SearchService."""
        # This method is called by SearchService for content searches
        results = self.backend.search_full_content(
            "login OR password",
            "test_dataset",
            limit=10,
            include_snippets=True
        )
        
        # Should return SearchServiceResult objects
        self.assertGreater(len(results), 0)
        result = results[0]
        self.assertEqual(result.file_path, "/project/src/auth.py")
        self.assertEqual(result.match_type, "content")
        self.assertIsNotNone(result.snippet)
        self.assertIsNotNone(result.metadata)
    
    def test_end_to_end_search_with_sanitization(self):
        """Test end-to-end search with query sanitization."""
        # Test potentially malicious query
        results = self.backend.search_metadata(
            'login"; DROP TABLE files; --',
            "test_dataset"
        )
        
        # Should still work (query sanitized)
        # The exact results depend on sanitization, but it shouldn't error
        self.assertIsInstance(results, list)
        
        # Verify database is still intact
        count = self.backend.get_dataset_file_count("test_dataset")
        self.assertEqual(count, 3)  # All files still there
    
    def test_search_with_custom_search_service(self):
        """Test that custom SearchService can be injected."""
        # Create mock search service
        mock_search_service = Mock(spec=SearchService)
        mock_search_service.search.return_value = []
        
        # Create backend with custom service
        backend2 = SqliteBackend(
            os.path.join(self.temp_dir, "test2.db"),
            search_service=mock_search_service
        )
        
        # Verify custom service is used
        self.assertEqual(backend2.search_service, mock_search_service)
        
        # Test search uses custom service
        backend2.search_metadata("test", "dataset")
        mock_search_service.search.assert_called_once()
        
        backend2.close()


if __name__ == '__main__':
    unittest.main()