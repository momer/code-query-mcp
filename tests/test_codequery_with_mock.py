"""Test CodeQueryServer with mock backend to demonstrate DI benefits."""

import unittest
from unittest.mock import Mock, MagicMock
from storage.sqlite_storage import CodeQueryServer
from storage.models import SearchResult, FileDocumentation


class TestCodeQueryWithMock(unittest.TestCase):
    """Test CodeQueryServer with mock backend."""
    
    def setUp(self):
        """Set up mock backend."""
        self.mock_backend = Mock()
        self.server = CodeQueryServer(storage_backend=self.mock_backend)
        self.server.setup_database()
        
    def test_search_delegates_to_backend(self):
        """Test search operations delegate to backend."""
        # Set up mock return value
        expected_results = [
            SearchResult(
                filepath="/test/file.py",
                filename="file.py",
                dataset="test-dataset",
                score=1.0,
                snippet="test snippet",
                overview="Test file"
            )
        ]
        self.mock_backend.search_metadata.return_value = expected_results
        
        # Call search
        results = self.server.search_files("query", "test-dataset")
        
        # Verify delegation
        self.mock_backend.search_metadata.assert_called_once_with("query", "test-dataset", 10)
        
        # Verify results
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filepath"], "/test/file.py")
        
    def test_insert_delegates_to_backend(self):
        """Test insert operations delegate to backend."""
        # Set up mock to return success
        self.mock_backend.insert_documentation.return_value = True
        
        # Call insert
        result = self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/new.py",
            filename="new.py",
            overview="New test file"
        )
        
        # Verify delegation
        self.mock_backend.insert_documentation.assert_called_once()
        call_args = self.mock_backend.insert_documentation.call_args[0][0]
        self.assertIsInstance(call_args, FileDocumentation)
        self.assertEqual(call_args.filepath, "/test/new.py")
        self.assertEqual(call_args.overview, "New test file")
        
        # Verify result
        self.assertTrue(result["success"])
        
    def test_error_handling_with_mock(self):
        """Test error handling when backend raises exceptions."""
        # Set up mock to raise exception
        self.mock_backend.search_metadata.side_effect = Exception("Database error")
        
        # Call search
        results = self.server.search_files("query", "test-dataset")
        
        # Should return empty results on error
        self.assertEqual(results, [])
        
    def test_get_file_with_partial_match(self):
        """Test get_file with mock backend returning multiple matches."""
        # Set up mock to return file
        expected_doc = FileDocumentation(
            filepath="/deeply/nested/file.py",
            filename="file.py",
            dataset="test-dataset",
            overview="Nested file"
        )
        self.mock_backend.get_file_documentation.return_value = expected_doc
        
        # Call get_file with partial path
        result = self.server.get_file("file.py", "test-dataset")
        
        # Verify result
        self.assertIsNotNone(result)
        self.assertEqual(result["filepath"], "/deeply/nested/file.py")
        
    def test_unified_search_with_mock(self):
        """Test unified search combines results correctly."""
        # Set up different results for metadata and content search
        metadata_results = [
            SearchResult(
                filepath="/test/meta.py",
                filename="meta.py", 
                dataset="test-dataset",
                score=1.0,
                snippet="metadata match",
                overview="Meta file",
                ddd_context="test"
            )
        ]
        content_only_results = [
            SearchResult(
                filepath="/test/content.py",
                filename="content.py",
                dataset="test-dataset", 
                score=0.8,
                snippet="content match",
                overview="Content file",
                ddd_context="test"
            )
        ]
        stats = {
            "unique_files": 2,
            "total_metadata_matches": 1
        }
        
        # Mock the unified search to return the expected tuple
        self.mock_backend.search_unified.return_value = (metadata_results, content_only_results, stats)
        
        # Call unified search
        result = self.server.search("query", "test-dataset")
        
        # Verify unified search was called
        self.mock_backend.search_unified.assert_called_once_with("query", "test-dataset", 10)
        
        # Verify results structure
        self.assertEqual(len(result["metadata_results"]), 1)
        self.assertEqual(len(result["content_results"]), 1)
        self.assertEqual(result["total_results"], 2)
        self.assertEqual(result["search_summary"]["total_unique_files"], 2)


if __name__ == '__main__':
    unittest.main()