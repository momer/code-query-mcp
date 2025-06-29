"""Integration tests for CodeQueryServer with StorageBackend."""

import unittest
import tempfile
import shutil
import os
from storage.sqlite_storage import CodeQueryServer


class TestCodeQueryIntegration(unittest.TestCase):
    """Test CodeQueryServer integration with StorageBackend."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        # Use the factory method for backward compatibility
        self.server = CodeQueryServer.from_db_path(self.db_path, self.temp_dir)
        self.server.setup_database()
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_server_initialization(self):
        """Test server initializes with storage backend."""
        self.assertIsNotNone(self.server.storage_backend)
        self.assertIsNotNone(self.server.db)  # Legacy compatibility
        
    def test_search_integration(self):
        """Test search methods work with storage backend."""
        # Insert a test document
        result = self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/example.py",
            filename="example.py",
            overview="Example Python file",
            functions={"test_func": {"description": "Test function"}},
            ddd_context="test-domain"
        )
        self.assertTrue(result["success"])
        
        # Test metadata search
        results = self.server.search_files("example", "test-dataset")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filepath"], "/test/example.py")
        
        # Test unified search
        search_result = self.server.search("example", "test-dataset")
        self.assertEqual(len(search_result["metadata_results"]), 1)
        self.assertEqual(search_result["total_results"], 1)
        
    def test_file_operations(self):
        """Test file operations with storage backend."""
        # Insert a test document
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/file.py",
            filename="file.py",
            overview="Test file",
            functions={"func1": {"description": "Function 1"}}
        )
        
        # Get file
        file_data = self.server.get_file("/test/file.py", "test-dataset")
        self.assertIsNotNone(file_data)
        self.assertEqual(file_data["filepath"], "/test/file.py")
        self.assertEqual(file_data["overview"], "Test file")
        self.assertIn("func1", file_data["functions"])
        
        # Update file
        update_result = self.server.update_file_documentation(
            "test-dataset",
            "/test/file.py",
            overview="Updated test file",
            functions={"func1": {"description": "Updated function"}, "func2": {"description": "New function"}}
        )
        self.assertTrue(update_result["success"])
        
        # Verify update
        updated_file = self.server.get_file("/test/file.py", "test-dataset")
        self.assertEqual(updated_file["overview"], "Updated test file")
        self.assertIn("func2", updated_file["functions"])
        
    def test_dataset_operations(self):
        """Test dataset operations with storage backend."""
        # Create dataset via insert
        self.server.insert_file_documentation(
            dataset_name="test-dataset-1",
            filepath="/test1/file.py",
            filename="file.py",
            overview="Test file 1"
        )
        
        self.server.insert_file_documentation(
            dataset_name="test-dataset-2",
            filepath="/test2/file.py",
            filename="file.py",
            overview="Test file 2"
        )
        
        # List datasets
        datasets = self.server.list_datasets()
        self.assertEqual(len(datasets), 2)
        dataset_names = [d["name"] for d in datasets]
        self.assertIn("test-dataset-1", dataset_names)
        self.assertIn("test-dataset-2", dataset_names)
        
        # Clear dataset
        clear_result = self.server.clear_dataset("test-dataset-1")
        self.assertTrue(clear_result["success"])
        self.assertEqual(clear_result["files_removed"], 1)
        
        # Verify dataset removed
        datasets_after = self.server.list_datasets()
        self.assertEqual(len(datasets_after), 1)
        self.assertEqual(datasets_after[0]["name"], "test-dataset-2")
        
    def test_status_integration(self):
        """Test status method with storage backend."""
        # Insert some data
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/file1.py",
            filename="file1.py",
            overview="File 1"
        )
        
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/file2.py",
            filename="file2.py",
            overview="File 2"
        )
        
        # Get status
        status = self.server.get_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["dataset_count"], 1)
        self.assertEqual(status["total_files"], 2)
        self.assertTrue(status["fts5_enabled"])
        self.assertIn("storage_info", status)
        
    def test_domain_listing(self):
        """Test DDD domain listing with storage backend."""
        # Insert files with different domains
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/auth.py",
            filename="auth.py",
            overview="Authentication",
            ddd_context="auth"
        )
        
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/user.py",
            filename="user.py",
            overview="User management",
            ddd_context="user"
        )
        
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/util.py",
            filename="util.py",
            overview="Utilities",
            ddd_context="auth"  # Same domain as first
        )
        
        # List domains
        domains = self.server.list_domains("test-dataset")
        self.assertEqual(len(domains), 2)
        self.assertIn("auth", domains)
        self.assertIn("user", domains)
        
    def test_partial_file_matching(self):
        """Test partial file path matching."""
        # Insert nested file
        self.server.insert_file_documentation(
            dataset_name="test-dataset",
            filepath="/test/deeply/nested/file.py",
            filename="file.py",
            overview="Nested file"
        )
        
        # Test partial match
        result = self.server.get_file("file.py", "test-dataset")
        self.assertIsNotNone(result)
        self.assertEqual(result["filepath"], "/test/deeply/nested/file.py")
        
        # Test with more specific partial path
        result2 = self.server.get_file("nested/file.py", "test-dataset")
        self.assertIsNotNone(result2)
        self.assertEqual(result2["filepath"], "/test/deeply/nested/file.py")


    def test_dependency_injection(self):
        """Test server can be initialized with injected storage backend."""
        from storage.sqlite_backend import SqliteBackend
        
        # Create backend separately
        backend = SqliteBackend(self.db_path)
        
        # Inject it into server
        server = CodeQueryServer(storage_backend=backend)
        server.setup_database()
        
        # Verify it works
        self.assertIsNotNone(server.storage_backend)
        self.assertEqual(server.storage_backend, backend)
        
        # Test that operations still work
        result = server.insert_file_documentation(
            dataset_name="test-di",
            filepath="/test/di.py",
            filename="di.py",
            overview="Dependency injection test"
        )
        self.assertTrue(result["success"])
        
        # Verify we can retrieve it
        file_data = server.get_file("/test/di.py", "test-di")
        self.assertIsNotNone(file_data)
        self.assertEqual(file_data["overview"], "Dependency injection test")


if __name__ == '__main__':
    unittest.main()