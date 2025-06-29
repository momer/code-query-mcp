"""Tests for storage data models (DTOs)."""

import unittest
import json
from datetime import datetime

from storage.models import (
    SearchResult,
    FileDocumentation,
    DatasetMetadata,
    BatchOperationResult
)


class TestSearchResult(unittest.TestCase):
    """Test SearchResult DTO."""
    
    def test_search_result_creation(self):
        """Test creating a SearchResult."""
        result = SearchResult(
            filepath="/test/file.py",
            filename="file.py",
            dataset="test_dataset",
            score=0.95,
            snippet="This is a [MATCH]test[/MATCH] snippet",
            overview="Test file",
            ddd_context="core"
        )
        
        self.assertEqual(result.filepath, "/test/file.py")
        self.assertEqual(result.filename, "file.py")
        self.assertEqual(result.dataset, "test_dataset")
        self.assertEqual(result.score, 0.95)
        self.assertEqual(result.snippet, "This is a [MATCH]test[/MATCH] snippet")
        self.assertEqual(result.overview, "Test file")
        self.assertEqual(result.ddd_context, "core")
        
    def test_search_result_to_dict(self):
        """Test SearchResult serialization to dict."""
        result = SearchResult(
            filepath="/test/file.py",
            filename="file.py",
            dataset="test_dataset",
            score=0.95,
            snippet="Test snippet"
        )
        
        data = result.to_dict()
        
        self.assertIsInstance(data, dict)
        self.assertEqual(data['filepath'], "/test/file.py")
        self.assertEqual(data['filename'], "file.py")
        self.assertEqual(data['dataset'], "test_dataset")
        self.assertEqual(data['score'], 0.95)
        self.assertEqual(data['snippet'], "Test snippet")
        self.assertIsNone(data['overview'])
        self.assertIsNone(data['ddd_context'])
        
    def test_search_result_optional_fields(self):
        """Test SearchResult with only required fields."""
        result = SearchResult(
            filepath="/test/file.py",
            filename="file.py",
            dataset="test_dataset",
            score=0.5,
            snippet="snippet"
        )
        
        self.assertIsNone(result.overview)
        self.assertIsNone(result.ddd_context)


class TestFileDocumentation(unittest.TestCase):
    """Test FileDocumentation DTO."""
    
    def test_file_documentation_creation(self):
        """Test creating FileDocumentation."""
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Test file overview",
            dataset="test_dataset",
            ddd_context="core",
            functions={"test_func": {"description": "Test function"}},
            exports={"TestClass": {"type": "class"}},
            imports={"os": {"source": "os"}},
            types_interfaces_classes={"TestType": {"type": "interface"}},
            constants={"TEST_CONST": {"value": "42"}},
            dependencies=["requests", "pytest"],
            other_notes=["Note 1", "Note 2"],
            full_content="# Test file\nprint('test')",
            documented_at_commit="abc123",
            documented_at=datetime.now()
        )
        
        self.assertEqual(doc.filepath, "/test/file.py")
        self.assertEqual(doc.filename, "file.py")
        self.assertEqual(doc.overview, "Test file overview")
        self.assertEqual(doc.dataset, "test_dataset")
        self.assertIsNotNone(doc.functions)
        self.assertIn("test_func", doc.functions)
        
    def test_file_documentation_to_sql_dict(self):
        """Test FileDocumentation conversion to SQL-ready dict."""
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Test overview",
            dataset="test_dataset",
            functions={"func": {"desc": "Function"}},
            exports={"exp": {"type": "function"}},
            dependencies=["dep1", "dep2"]
        )
        
        sql_dict = doc.to_sql_dict()
        
        # Check that JSON fields are serialized
        self.assertIsInstance(sql_dict['functions'], str)
        self.assertIsInstance(sql_dict['exports'], str)
        self.assertIsInstance(sql_dict['dependencies'], str)
        
        # Verify JSON is valid
        functions_data = json.loads(sql_dict['functions'])
        self.assertEqual(functions_data, {"func": {"desc": "Function"}})
        
        dependencies_data = json.loads(sql_dict['dependencies'])
        self.assertEqual(dependencies_data, ["dep1", "dep2"])
        
    def test_file_documentation_to_sql_tuple(self):
        """Test FileDocumentation conversion to SQL tuple."""
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Test overview",
            dataset="test_dataset"
        )
        
        sql_tuple = doc.to_sql_tuple()
        
        self.assertIsInstance(sql_tuple, tuple)
        self.assertEqual(len(sql_tuple), 14)  # Number of fields
        self.assertEqual(sql_tuple[0], "/test/file.py")  # filepath
        self.assertEqual(sql_tuple[1], "file.py")  # filename
        self.assertEqual(sql_tuple[2], "test_dataset")  # dataset
        self.assertEqual(sql_tuple[3], "Test overview")  # overview
        
    def test_file_documentation_from_sql_row(self):
        """Test creating FileDocumentation from SQL row."""
        # Simulate a SQL row result
        row = {
            'filepath': '/test/file.py',
            'filename': 'file.py',
            'dataset_id': 'test_dataset',  # Note: SQL uses dataset_id
            'overview': 'Test overview',
            'ddd_context': 'core',
            'functions': '{"func": {"desc": "Test"}}',
            'exports': '{"exp": {"type": "function"}}',
            'imports': None,
            'types_interfaces_classes': None,
            'constants': None,
            'dependencies': '["dep1"]',
            'other_notes': '["note1"]',
            'full_content': '# Test',
            'documented_at_commit': 'abc123',
            'documented_at': datetime.now()
        }
        
        doc = FileDocumentation.from_sql_row(row)
        
        self.assertEqual(doc.filepath, '/test/file.py')
        self.assertEqual(doc.filename, 'file.py')
        self.assertEqual(doc.dataset, 'test_dataset')  # Mapped from dataset_id
        self.assertEqual(doc.overview, 'Test overview')
        self.assertEqual(doc.functions, {"func": {"desc": "Test"}})
        self.assertEqual(doc.exports, {"exp": {"type": "function"}})
        self.assertEqual(doc.dependencies, ["dep1"])
        self.assertEqual(doc.other_notes, ["note1"])
        
    def test_file_documentation_minimal(self):
        """Test FileDocumentation with only required fields."""
        doc = FileDocumentation(
            filepath="/test/file.py",
            filename="file.py",
            overview="Overview",
            dataset="dataset"
        )
        
        self.assertIsNone(doc.ddd_context)
        self.assertIsNone(doc.functions)
        self.assertIsNone(doc.exports)
        self.assertIsNone(doc.full_content)


class TestDatasetMetadata(unittest.TestCase):
    """Test DatasetMetadata DTO."""
    
    def test_dataset_metadata_creation(self):
        """Test creating DatasetMetadata."""
        now = datetime.now()
        metadata = DatasetMetadata(
            dataset_id="test_dataset",
            source_dir="/test/source",
            files_count=42,
            loaded_at=now,
            dataset_type="worktree",
            parent_dataset_id="parent_dataset",
            source_branch="feature/test"
        )
        
        self.assertEqual(metadata.dataset_id, "test_dataset")
        self.assertEqual(metadata.source_dir, "/test/source")
        self.assertEqual(metadata.files_count, 42)
        self.assertEqual(metadata.loaded_at, now)
        self.assertEqual(metadata.dataset_type, "worktree")
        self.assertEqual(metadata.parent_dataset_id, "parent_dataset")
        self.assertEqual(metadata.source_branch, "feature/test")
        
    def test_dataset_metadata_defaults(self):
        """Test DatasetMetadata default values."""
        metadata = DatasetMetadata(
            dataset_id="test",
            source_dir="/test",
            files_count=0,
            loaded_at=datetime.now()
        )
        
        self.assertEqual(metadata.dataset_type, "main")
        self.assertIsNone(metadata.parent_dataset_id)
        self.assertIsNone(metadata.source_branch)
        
    def test_dataset_metadata_to_dict(self):
        """Test DatasetMetadata serialization."""
        now = datetime.now()
        metadata = DatasetMetadata(
            dataset_id="test",
            source_dir="/test",
            files_count=10,
            loaded_at=now
        )
        
        data = metadata.to_dict()
        
        self.assertIsInstance(data, dict)
        self.assertEqual(data['dataset_id'], "test")
        self.assertEqual(data['source_dir'], "/test")
        self.assertEqual(data['files_count'], 10)
        self.assertEqual(data['loaded_at'], now.isoformat())
        self.assertEqual(data['dataset_type'], "main")


class TestBatchOperationResult(unittest.TestCase):
    """Test BatchOperationResult DTO."""
    
    def test_batch_result_creation(self):
        """Test creating BatchOperationResult."""
        result = BatchOperationResult(
            total_items=100,
            successful=95,
            failed=5
        )
        
        self.assertEqual(result.total_items, 100)
        self.assertEqual(result.successful, 95)
        self.assertEqual(result.failed, 5)
        self.assertEqual(len(result.error_details), 0)
        
    def test_batch_result_add_error(self):
        """Test adding error details."""
        result = BatchOperationResult(
            total_items=10,
            successful=8,
            failed=2
        )
        
        result.add_error("file1.py", "Permission denied")
        result.add_error("file2.py", "File not found")
        
        self.assertEqual(len(result.error_details), 2)
        self.assertEqual(result.error_details[0]['item_id'], "file1.py")
        self.assertEqual(result.error_details[0]['error'], "Permission denied")
        self.assertEqual(result.error_details[1]['item_id'], "file2.py")
        self.assertEqual(result.error_details[1]['error'], "File not found")
        
    def test_batch_result_success_rate(self):
        """Test success rate calculation."""
        # 100% success
        result = BatchOperationResult(total_items=10, successful=10, failed=0)
        self.assertEqual(result.success_rate, 100.0)
        
        # 50% success
        result = BatchOperationResult(total_items=10, successful=5, failed=5)
        self.assertEqual(result.success_rate, 50.0)
        
        # 0% success
        result = BatchOperationResult(total_items=10, successful=0, failed=10)
        self.assertEqual(result.success_rate, 0.0)
        
        # Empty batch
        result = BatchOperationResult(total_items=0, successful=0, failed=0)
        self.assertEqual(result.success_rate, 0.0)
        
    def test_batch_result_with_errors(self):
        """Test batch result with error tracking."""
        result = BatchOperationResult(
            total_items=3,
            successful=1,
            failed=2,
            error_details=[
                {'item_id': 'file1', 'error': 'Error 1'},
                {'item_id': 'file2', 'error': 'Error 2'}
            ]
        )
        
        self.assertEqual(result.total_items, 3)
        self.assertEqual(result.successful, 1)
        self.assertEqual(result.failed, 2)
        self.assertEqual(len(result.error_details), 2)
        self.assertAlmostEqual(result.success_rate, 33.33, places=1)


if __name__ == '__main__':
    unittest.main()