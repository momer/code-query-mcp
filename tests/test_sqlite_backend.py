"""Tests for SQLite backend implementation."""

import unittest
import tempfile
import shutil
import os
from datetime import datetime

from storage.sqlite_backend import SqliteBackend
from storage.models import FileDocumentation, DatasetMetadata, BatchOperationResult


class TestSqliteBackend(unittest.TestCase):
    """Test SqliteBackend functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        self.backend = SqliteBackend(self.db_path)
        
    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'backend'):
            self.backend.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_backend_initialization(self):
        """Test backend initializes properly."""
        self.assertTrue(os.path.exists(self.db_path))
        
        # Check schema version
        version = self.backend.get_schema_version()
        self.assertIsNotNone(version)
        
    def test_dataset_operations(self):
        """Test dataset creation, retrieval, and deletion."""
        # Create dataset
        success = self.backend.create_dataset(
            dataset_id="test-dataset",
            source_dir="/test/src",
            dataset_type="main"
        )
        self.assertTrue(success)
        
        # Retrieve dataset
        metadata = self.backend.get_dataset_metadata("test-dataset")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.dataset_id, "test-dataset")
        self.assertEqual(metadata.source_dir, "/test/src")
        self.assertEqual(metadata.dataset_type, "main")
        
        # List datasets
        datasets = self.backend.list_datasets()
        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0].dataset_id, "test-dataset")
        
        # Delete dataset
        success = self.backend.delete_dataset("test-dataset")
        self.assertTrue(success)
        
        # Verify deletion
        metadata = self.backend.get_dataset_metadata("test-dataset")
        self.assertIsNone(metadata)
        
    def test_document_insert_and_retrieve(self):
        """Test inserting and retrieving file documentation."""
        # Create dataset first
        self.backend.create_dataset("test-dataset", "/test")
        
        # Create documentation
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Test file overview",
            dataset="test-dataset",
            ddd_context="core",
            functions={"test_func": {"description": "Test function"}},
            exports={"TestClass": {"type": "class"}},
            imports={"os": {"source": "os"}},
            dependencies=["requests", "pytest"],
            other_notes=["Note 1", "Note 2"],
            full_content="# Test file\nprint('test')",
            documented_at_commit="abc123"
        )
        
        # Insert
        success = self.backend.insert_documentation(doc)
        self.assertTrue(success)
        
        # Retrieve without content
        retrieved = self.backend.get_file_documentation("/test/file.py", "test-dataset")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.filepath, "/test/file.py")
        self.assertEqual(retrieved.overview, "Test file overview")
        self.assertEqual(retrieved.functions, {"test_func": {"description": "Test function"}})
        self.assertIsNone(retrieved.full_content)  # Not requested
        
        # Retrieve with content
        retrieved = self.backend.get_file_documentation("/test/file.py", "test-dataset", include_content=True)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.full_content, "# Test file\nprint('test')")
        
    def test_document_update(self):
        """Test updating existing documentation."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Original overview",
            dataset="test-dataset"
        )
        self.backend.insert_documentation(doc)
        
        # Update
        updates = {
            "overview": "Updated overview",
            "ddd_context": "updated-context",
            "functions": {"new_func": {"description": "New function"}}
        }
        success = self.backend.update_documentation("/test/file.py", "test-dataset", updates)
        self.assertTrue(success)
        
        # Verify update
        retrieved = self.backend.get_file_documentation("/test/file.py", "test-dataset")
        self.assertEqual(retrieved.overview, "Updated overview")
        self.assertEqual(retrieved.ddd_context, "updated-context")
        self.assertEqual(retrieved.functions, {"new_func": {"description": "New function"}})
        
    def test_document_deletion(self):
        """Test deleting documentation."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Test",
            dataset="test-dataset"
        )
        self.backend.insert_documentation(doc)
        
        # Delete
        success = self.backend.delete_documentation("/test/file.py", "test-dataset")
        self.assertTrue(success)
        
        # Verify deletion
        retrieved = self.backend.get_file_documentation("/test/file.py", "test-dataset")
        self.assertIsNone(retrieved)
        
    def test_batch_insert(self):
        """Test batch insert operations."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        
        # Create multiple documents
        docs = []
        for i in range(10):
            docs.append(FileDocumentation(
                filepath=f"/test/file{i}.py",
                filename=f"file{i}.py",
                overview=f"File {i} overview",
                dataset="test-dataset",
                functions={f"func{i}": {"description": f"Function {i}"}}
            ))
            
        # Batch insert
        result = self.backend.insert_documentation_batch(docs)
        
        self.assertIsInstance(result, BatchOperationResult)
        self.assertEqual(result.total_items, 10)
        self.assertEqual(result.successful, 10)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.success_rate, 100.0)
        
        # Verify all inserted
        files = self.backend.get_dataset_files("test-dataset")
        self.assertEqual(len(files), 10)
        
    def test_search_metadata(self):
        """Test metadata search functionality."""
        # Setup test data
        self.backend.create_dataset("test-dataset", "/test")
        
        docs = [
            FileDocumentation(
                filepath="/test/auth/login.py",
                filename="login.py",
                overview="User authentication and login functionality",
                dataset="test-dataset",
                functions={"authenticate": {"description": "Authenticate user credentials"}},
                exports={"LoginForm": {"type": "class"}}
            ),
            FileDocumentation(
                filepath="/test/utils/helpers.py",
                filename="helpers.py",
                overview="Utility helper functions",
                dataset="test-dataset",
                functions={"format_date": {"description": "Format date strings"}}
            ),
            FileDocumentation(
                filepath="/test/auth/register.py",
                filename="register.py",
                overview="User registration functionality",
                dataset="test-dataset",
                functions={"create_user": {"description": "Create new user account"}}
            )
        ]
        
        for doc in docs:
            self.backend.insert_documentation(doc)
            
        # Search for "auth"
        results = self.backend.search_metadata("auth", "test-dataset")
        
        self.assertGreaterEqual(len(results), 2)  # Should find login.py and register.py
        filepaths = [r.filepath for r in results]
        self.assertIn("/test/auth/login.py", filepaths)
        self.assertIn("/test/auth/register.py", filepaths)
        
        # Check result structure
        first_result = results[0]
        self.assertIsNotNone(first_result.snippet)
        self.assertIsNotNone(first_result.score)
        self.assertIsNotNone(first_result.overview)
        
    def test_search_content(self):
        """Test full content search functionality."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        
        docs = [
            FileDocumentation(
                filepath="/test/example1.py",
                filename="example1.py",
                overview="Example file 1",
                dataset="test-dataset",
                full_content="def process_payment():\n    # Process payment transaction\n    pass"
            ),
            FileDocumentation(
                filepath="/test/example2.py",
                filename="example2.py",
                overview="Example file 2",
                dataset="test-dataset",
                full_content="def calculate_total():\n    # Calculate order total\n    pass"
            )
        ]
        
        for doc in docs:
            self.backend.insert_documentation(doc)
            
        # Search content
        results = self.backend.search_content("payment", "test-dataset")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].filepath, "/test/example1.py")
        self.assertIn("payment", results[0].snippet.lower())
        
    def test_search_unified(self):
        """Test unified search with deduplication."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        
        # Document with "payment" in both metadata and content
        doc1 = FileDocumentation(
            filepath="/test/payment.py",
            filename="payment.py",
            overview="Payment processing module",
            dataset="test-dataset",
            full_content="def process_payment():\n    pass"
        )
        
        # Document with "transaction" only in content (not in metadata)
        doc2 = FileDocumentation(
            filepath="/test/helper.py",
            filename="helper.py",
            overview="General helper functions",
            dataset="test-dataset",
            full_content="def validate_transaction(amount):\n    # Validate transaction amount\n    pass"
        )
        
        self.backend.insert_documentation(doc1)
        self.backend.insert_documentation(doc2)
        
        # Test 1: Search for "payment" - should find in metadata
        metadata_results, content_only_results, stats = self.backend.search_unified("payment", "test-dataset")
        
        # Should find payment.py in metadata results
        self.assertEqual(len(metadata_results), 1)
        self.assertEqual(metadata_results[0].filepath, "/test/payment.py")
        self.assertEqual(len(content_only_results), 0)  # No content-only matches
        
        # Test 2: Search for "transaction" - should find only in content
        metadata_results, content_only_results, stats = self.backend.search_unified("transaction", "test-dataset")
        
        # Should find helper.py only in content results
        self.assertEqual(len(metadata_results), 0)  # Not in metadata
        self.assertEqual(len(content_only_results), 1)
        self.assertEqual(content_only_results[0].filepath, "/test/helper.py")
        
        # Check stats
        self.assertIsInstance(stats, dict)
        self.assertIn('total_metadata_matches', stats)
        self.assertIn('total_content_matches', stats)
        self.assertIn('unique_files', stats)
        self.assertIn('duplicate_matches', stats)
        
    def test_dataset_file_operations(self):
        """Test dataset file listing and counting."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        
        # Insert some files
        for i in range(5):
            doc = FileDocumentation(
                filepath=f"/test/file{i}.py",
                filename=f"file{i}.py",
                overview=f"File {i}",
                dataset="test-dataset"
            )
            self.backend.insert_documentation(doc)
            
        # Test file listing
        files = self.backend.get_dataset_files("test-dataset")
        self.assertEqual(len(files), 5)
        self.assertTrue(all(f.startswith("/test/file") for f in files))
        
        # Test with limit
        files = self.backend.get_dataset_files("test-dataset", limit=3)
        self.assertEqual(len(files), 3)
        
        # Test file count
        count = self.backend.get_dataset_file_count("test-dataset")
        self.assertEqual(count, 5)
        
    def test_storage_info(self):
        """Test storage information retrieval."""
        info = self.backend.get_storage_info()
        
        self.assertIsInstance(info, dict)
        self.assertIn('db_path', info)
        self.assertIn('db_size_bytes', info)
        self.assertIn('total_files', info)
        self.assertIn('total_datasets', info)
        self.assertIn('schema_version', info)
        self.assertIn('connection_pool_stats', info)
        
        # Verify values
        self.assertEqual(info['db_path'], self.db_path)
        self.assertGreaterEqual(info['db_size_bytes'], 0)
        self.assertEqual(info['total_files'], 0)  # No files inserted yet
        self.assertEqual(info['total_datasets'], 0)  # No datasets created yet
        
    def test_partial_path_matching(self):
        """Test partial path matching in get_file_documentation."""
        # Setup
        self.backend.create_dataset("test-dataset", "/test")
        doc = FileDocumentation(
            filepath="/test/deeply/nested/file.py",
            filename="file.py",
            overview="Nested file",
            dataset="test-dataset"
        )
        self.backend.insert_documentation(doc)
        
        # Test partial path
        retrieved = self.backend.get_file_documentation("file.py", "test-dataset")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.filepath, "/test/deeply/nested/file.py")
        
        # Test with more specific partial path
        retrieved = self.backend.get_file_documentation("nested/file.py", "test-dataset")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.filepath, "/test/deeply/nested/file.py")
        
    def test_worktree_dataset(self):
        """Test worktree dataset creation with parent."""
        # Create main dataset
        self.backend.create_dataset("project-main", "/project", dataset_type="main")
        
        # Create worktree dataset
        success = self.backend.create_dataset(
            dataset_id="project-feature",
            source_dir="/project-worktree",
            dataset_type="worktree",
            parent_id="project-main",
            source_branch="feature/new-feature"
        )
        self.assertTrue(success)
        
        # Verify metadata
        metadata = self.backend.get_dataset_metadata("project-feature")
        self.assertEqual(metadata.dataset_type, "worktree")
        self.assertEqual(metadata.parent_dataset_id, "project-main")
        self.assertEqual(metadata.source_branch, "feature/new-feature")
        
    def test_error_handling(self):
        """Test error handling for various edge cases."""
        # Try to get non-existent dataset
        metadata = self.backend.get_dataset_metadata("non-existent")
        self.assertIsNone(metadata)
        
        # Try to create duplicate dataset
        self.backend.create_dataset("test-dataset", "/test")
        success = self.backend.create_dataset("test-dataset", "/test2")
        self.assertFalse(success)
        
        # Try to delete non-existent dataset
        success = self.backend.delete_dataset("non-existent")
        self.assertFalse(success)


if __name__ == '__main__':
    unittest.main()