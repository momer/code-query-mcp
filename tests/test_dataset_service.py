"""Tests for dataset service implementation."""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime
import tempfile
import os

from dataset.dataset_service import DatasetService
from dataset.dataset_models import (
    Dataset, DatasetType, SyncDirection, SyncOperation,
    DatasetStats, DatasetDiff, DatasetValidationError
)
from dataset.dataset_validator import DatasetValidator
from dataset.worktree_handler import WorktreeHandler
from dataset.dataset_sync import DatasetSynchronizer
from storage.backend import StorageBackend
from storage.models import DatasetMetadata, FileDocumentation


class TestDatasetService(unittest.TestCase):
    """Test DatasetService functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_storage = Mock(spec=StorageBackend)
        self.mock_git = Mock()
        self.service = DatasetService(self.mock_storage, self.mock_git)
        
        # Create a temporary directory for tests
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_create_dataset_success(self):
        """Test successful dataset creation."""
        # Mock storage responses
        self.mock_storage.get_dataset_metadata.return_value = None  # Not exists
        self.mock_storage.create_dataset.return_value = True
        
        # Mock the created dataset metadata
        created_metadata = DatasetMetadata(
            dataset_id="test-dataset",
            source_dir=self.temp_dir,
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=0
        )
        self.mock_storage.get_dataset_metadata.side_effect = [None, created_metadata]
        
        # Create dataset
        dataset = self.service.create_dataset("test-dataset", self.temp_dir)
        
        # Verify
        self.assertEqual(dataset.dataset_id, "test-dataset")
        self.assertEqual(dataset.dataset_type, DatasetType.MAIN)
        self.mock_storage.create_dataset.assert_called_once_with(
            dataset_id="test-dataset",
            source_dir=self.temp_dir,
            dataset_type="main",
            parent_id=None,
            source_branch=None
        )
        
    def test_create_dataset_already_exists(self):
        """Test dataset creation when it already exists."""
        # Mock existing dataset
        existing = DatasetMetadata(
            dataset_id="test-dataset",
            source_dir="/some/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=10
        )
        self.mock_storage.get_dataset_metadata.return_value = existing
        
        # Should raise validation error
        with self.assertRaises(DatasetValidationError) as ctx:
            self.service.create_dataset("test-dataset", self.temp_dir)
        
        self.assertIn("already exists", str(ctx.exception))
        
    def test_create_dataset_invalid_name(self):
        """Test dataset creation with invalid name."""
        # Should raise validation error for invalid name
        with self.assertRaises(DatasetValidationError) as ctx:
            self.service.create_dataset("test dataset", self.temp_dir)  # Space not allowed
        
        self.assertIn("alphanumeric", str(ctx.exception))
        
    def test_create_dataset_nonexistent_directory(self):
        """Test dataset creation with non-existent directory."""
        with self.assertRaises(DatasetValidationError) as ctx:
            self.service.create_dataset("test-dataset", "/nonexistent/path")
        
        self.assertIn("does not exist", str(ctx.exception))
        
    def test_create_worktree_dataset(self):
        """Test automatic worktree detection."""
        # Mock worktree detection
        self.service.worktree_handler.is_worktree = Mock(return_value=True)
        self.service.worktree_handler.get_worktree_branch = Mock(return_value="feature-branch")
        
        self.mock_storage.get_dataset_metadata.return_value = None
        self.mock_storage.create_dataset.return_value = True
        
        # Mock the created dataset
        created_metadata = DatasetMetadata(
            dataset_id="test-dataset",
            source_dir=self.temp_dir,
            dataset_type="worktree",
            source_branch="feature-branch",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=0
        )
        self.mock_storage.get_dataset_metadata.side_effect = [None, created_metadata]
        
        # Create dataset
        dataset = self.service.create_dataset("test-dataset", self.temp_dir)
        
        # Verify worktree type was set
        self.mock_storage.create_dataset.assert_called_once_with(
            dataset_id="test-dataset",
            source_dir=self.temp_dir,
            dataset_type="worktree",
            parent_id=None,
            source_branch="feature-branch"
        )
        
    def test_fork_dataset_success(self):
        """Test successful dataset forking."""
        # Mock source dataset
        source_metadata = DatasetMetadata(
            dataset_id="source-dataset",
            source_dir="/source/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        # Mock the forked dataset metadata
        forked_metadata = DatasetMetadata(
            dataset_id="forked-dataset",
            source_dir="/source/path",
            dataset_type="fork",
            parent_dataset_id="source-dataset",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        # Mock transaction context
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.get_dataset_metadata.side_effect = [
            None,  # First call - check if exists
            forked_metadata  # Second call - return created dataset
        ]
        mock_txn_storage.create_dataset.return_value = True
        
        # Set up mocks
        self.mock_storage.get_dataset_metadata.side_effect = [
            source_metadata,  # First call to check source exists
            forked_metadata   # Second call to return forked dataset
        ]
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Mock synchronizer
        with patch('dataset.dataset_service.DatasetSynchronizer') as MockSync:
            mock_sync = MockSync.return_value
            mock_sync.copy_all_documentation.return_value = 5
            
            # Fork dataset
            forked = self.service.fork_dataset("source-dataset", "forked-dataset")
            
            # Verify
            self.assertEqual(forked.dataset_id, "forked-dataset")
            self.assertEqual(forked.dataset_type, DatasetType.FORK)
            self.assertEqual(forked.parent_dataset_id, "source-dataset")
            
            # Verify documentation was copied
            mock_sync.copy_all_documentation.assert_called_once_with(
                "source-dataset", "forked-dataset"
            )
            
    def test_fork_dataset_source_not_found(self):
        """Test forking when source dataset doesn't exist."""
        self.mock_storage.get_dataset_metadata.return_value = None
        
        with self.assertRaises(ValueError) as ctx:
            self.service.fork_dataset("nonexistent", "target")
        
        self.assertIn("not found", str(ctx.exception))
        
    def test_sync_datasets_success(self):
        """Test successful dataset synchronization."""
        # Mock datasets
        source = DatasetMetadata(
            dataset_id="source",
            source_dir="/source",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=10
        )
        target = DatasetMetadata(
            dataset_id="target",
            source_dir="/target",
            dataset_type="fork",
            parent_dataset_id="source",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=8
        )
        
        self.mock_storage.get_dataset_metadata.side_effect = [source, target]
        
        # Mock synchronizer
        with patch.object(self.service.synchronizer, 'sync_changes', return_value=3):
            # Sync datasets
            sync_op = self.service.sync_datasets(
                "source", "target", "main", "feature-branch"
            )
            
            # Verify
            self.assertEqual(sync_op.source_dataset_id, "source")
            self.assertEqual(sync_op.target_dataset_id, "target")
            self.assertEqual(sync_op.files_synced, 3)
            self.assertTrue(sync_op.is_successful())
            
    def test_sync_datasets_bidirectional_not_implemented(self):
        """Test bidirectional sync raises NotImplementedError."""
        # Mock datasets
        source = DatasetMetadata(
            dataset_id="source",
            source_dir="/source",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=10
        )
        target = DatasetMetadata(
            dataset_id="target",
            source_dir="/target",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=10
        )
        
        self.mock_storage.get_dataset_metadata.side_effect = [source, target]
        
        # Should raise NotImplementedError
        with self.assertRaises(NotImplementedError) as ctx:
            self.service.sync_datasets(
                "source", "target", "main", "main",
                direction=SyncDirection.BIDIRECTIONAL
            )
        
        self.assertIn("not yet supported", str(ctx.exception))
        
    def test_delete_dataset_success(self):
        """Test successful dataset deletion."""
        # Mock dataset
        dataset = DatasetMetadata(
            dataset_id="to-delete",
            source_dir="/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        # Mock transaction
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.list_datasets.return_value = []  # No children
        mock_txn_storage.delete_all_documentation.return_value = 5
        mock_txn_storage.delete_dataset.return_value = True
        
        self.mock_storage.get_dataset_metadata.return_value = dataset
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Delete dataset
        result = self.service.delete_dataset("to-delete")
        
        # Verify
        self.assertTrue(result)
        mock_txn_storage.delete_all_documentation.assert_called_once_with("to-delete")
        mock_txn_storage.delete_dataset.assert_called_once_with("to-delete")
        
    def test_delete_dataset_with_children_no_force(self):
        """Test deletion fails when dataset has children and force=False."""
        # Mock dataset with children
        parent = DatasetMetadata(
            dataset_id="parent",
            source_dir="/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        child = DatasetMetadata(
            dataset_id="child",
            source_dir="/path",
            dataset_type="fork",
            parent_dataset_id="parent",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=3
        )
        
        # Mock transaction
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.list_datasets.return_value = [parent, child]
        
        self.mock_storage.get_dataset_metadata.return_value = parent
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Should raise ValueError
        with self.assertRaises(ValueError) as ctx:
            self.service.delete_dataset("parent", force=False)
            
        self.assertIn("child datasets", str(ctx.exception))
            
    def test_delete_dataset_with_children_force(self):
        """Test force deletion of dataset with children."""
        # Mock dataset with children
        parent = DatasetMetadata(
            dataset_id="parent",
            source_dir="/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        child = DatasetMetadata(
            dataset_id="child",
            source_dir="/path",
            dataset_type="fork",
            parent_dataset_id="parent",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=3
        )
        
        # Mock transaction
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.list_datasets.return_value = [parent, child]
        mock_txn_storage.delete_all_documentation.return_value = 5
        mock_txn_storage.delete_dataset.return_value = True
        
        self.mock_storage.get_dataset_metadata.return_value = parent
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Delete with force=True should succeed
        result = self.service.delete_dataset("parent", force=True)
        
        # Verify
        self.assertTrue(result)
        mock_txn_storage.delete_all_documentation.assert_called_once_with("parent")
        mock_txn_storage.delete_dataset.assert_called_once_with("parent")
            
    def test_fork_dataset_transaction_rollback(self):
        """Test transaction rollback when forking fails."""
        # Mock source dataset
        source_metadata = DatasetMetadata(
            dataset_id="source-dataset",
            source_dir="/source/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        # Mock transaction context
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.get_dataset_metadata.return_value = None  # Dataset doesn't exist
        mock_txn_storage.create_dataset.side_effect = RuntimeError("Database error")
        
        # Set up mocks
        self.mock_storage.get_dataset_metadata.return_value = source_metadata
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Fork should raise exception
        with self.assertRaises(RuntimeError) as ctx:
            self.service.fork_dataset("source-dataset", "forked-dataset")
        
        self.assertIn("Database error", str(ctx.exception))
        
        # Verify transaction was rolled back (exit was called with exception)
        exit_call_args = self.mock_storage.transaction.return_value.__exit__.call_args
        self.assertIsNotNone(exit_call_args[0][0])  # exc_type should not be None
            
    def test_delete_dataset_transaction_rollback(self):
        """Test transaction rollback when deletion fails."""
        # Mock dataset
        dataset = DatasetMetadata(
            dataset_id="to-delete",
            source_dir="/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        
        # Mock transaction
        mock_txn_storage = Mock(spec=StorageBackend)
        mock_txn_storage.list_datasets.return_value = []  # No children
        mock_txn_storage.delete_all_documentation.return_value = 5
        mock_txn_storage.delete_dataset.side_effect = RuntimeError("Delete failed")
        
        self.mock_storage.get_dataset_metadata.return_value = dataset
        self.mock_storage.transaction.return_value.__enter__ = Mock(return_value=mock_txn_storage)
        self.mock_storage.transaction.return_value.__exit__ = Mock(return_value=None)
        
        # Delete should raise exception
        with self.assertRaises(RuntimeError) as ctx:
            self.service.delete_dataset("to-delete")
        
        self.assertIn("Delete failed", str(ctx.exception))
        
        # Verify transaction was rolled back
        exit_call_args = self.mock_storage.transaction.return_value.__exit__.call_args
        self.assertIsNotNone(exit_call_args[0][0])  # exc_type should not be None
            
    def test_get_dataset_stats(self):
        """Test getting dataset statistics."""
        # Mock dataset
        dataset = DatasetMetadata(
            dataset_id="test-dataset",
            source_dir="/path",
            dataset_type="main",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=10
        )
        
        # Mock stats
        expected_stats = DatasetStats(
            dataset_id="test-dataset",
            total_files=10,
            total_size_bytes=1024000,
            last_updated=datetime.now(),
            file_types={'.py': 5, '.md': 3, '.txt': 2},
            largest_files=[('large.py', 10000), ('README.md', 5000)]
        )
        
        self.mock_storage.get_dataset_metadata.return_value = dataset
        self.mock_storage.get_dataset_statistics.return_value = expected_stats
        
        # Get stats
        stats = self.service.get_dataset_stats("test-dataset")
        
        # Verify
        self.assertEqual(stats.dataset_id, "test-dataset")
        self.assertEqual(stats.total_files, 10)
        self.assertEqual(stats.total_size_bytes, 1024000)
        self.assertEqual(stats.file_types['.py'], 5)
        
    def test_get_dataset_diff(self):
        """Test comparing two datasets."""
        # Mock file lists
        self.mock_storage.get_dataset_files.side_effect = [
            ['file1.py', 'file2.py', 'file3.py'],  # dataset1
            ['file2.py', 'file3.py', 'file4.py']   # dataset2
        ]
        
        # Mock file documentation for common files
        doc1_file2 = FileDocumentation(
            filepath='file2.py',
            filename='file2.py',
            overview='File 2 overview',
            dataset='dataset1',
            content_hash='hash1',
            documented_at=datetime.now()
        )
        doc2_file2 = FileDocumentation(
            filepath='file2.py',
            filename='file2.py',
            overview='File 2 overview',
            dataset='dataset2',
            content_hash='hash1',  # Same hash
            documented_at=datetime.now()
        )
        
        doc1_file3 = FileDocumentation(
            filepath='file3.py',
            filename='file3.py',
            overview='File 3 overview',
            dataset='dataset1',
            content_hash='hash3a',
            documented_at=datetime.now()
        )
        doc2_file3 = FileDocumentation(
            filepath='file3.py',
            filename='file3.py',
            overview='File 3 overview',
            dataset='dataset2',
            content_hash='hash3b',  # Different hash
            documented_at=datetime.now()
        )
        
        # Mock batch documentation retrieval
        self.mock_storage.get_file_documentation_batch.side_effect = [
            {'file2.py': doc1_file2, 'file3.py': doc1_file3},  # dataset1
            {'file2.py': doc2_file2, 'file3.py': doc2_file3}   # dataset2
        ]
        
        # Get diff
        diff = self.service.get_dataset_diff("dataset1", "dataset2")
        
        # Verify
        self.assertEqual(diff.deleted_files, ['file1.py'])
        self.assertEqual(diff.added_files, ['file4.py'])
        self.assertEqual(diff.modified_files, ['file3.py'])
        self.assertEqual(diff.total_changes, 3)
        
    def test_cleanup_orphaned_datasets_dry_run(self):
        """Test finding orphaned datasets without deleting."""
        # Mock worktree datasets
        wt1 = DatasetMetadata(
            dataset_id="main__wt_feature1",
            source_dir="/worktree1",
            dataset_type="worktree",
            source_branch="feature1",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=5
        )
        wt2 = DatasetMetadata(
            dataset_id="main__wt_feature2",
            source_dir="/worktree2",
            dataset_type="worktree",
            source_branch="feature2",
            loaded_at=datetime.now(),
            updated_at=datetime.now(),
            files_count=3
        )
        
        self.mock_storage.list_datasets.return_value = [wt1, wt2]
        
        # Mock worktree existence check
        with patch.object(self.service, 'list_datasets') as mock_list:
            mock_list.return_value = [
                Dataset(
                    dataset_id="main__wt_feature1",
                    source_dir="/worktree1",
                    dataset_type=DatasetType.WORKTREE,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    source_branch="feature1"
                ),
                Dataset(
                    dataset_id="main__wt_feature2",
                    source_dir="/worktree2",
                    dataset_type=DatasetType.WORKTREE,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    source_branch="feature2"
                )
            ]
            
            # Mock that first worktree still exists, second doesn't
            self.service.worktree_handler.worktree_exists = Mock(side_effect=[True, False])
            
            # Run cleanup
            orphans = self.service.cleanup_orphaned_datasets(dry_run=True)
            
            # Verify
            self.assertEqual(orphans, ["main__wt_feature2"])
            # Should not actually delete in dry run
            self.mock_storage.delete_dataset.assert_not_called()


class TestDatasetValidator(unittest.TestCase):
    """Test DatasetValidator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = DatasetValidator()
        
    def test_validate_dataset_name_valid(self):
        """Test valid dataset names."""
        valid_names = [
            "my-dataset",
            "dataset_123",
            "MyDataset",
            "a",
            "123dataset"
        ]
        
        for name in valid_names:
            try:
                self.validator.validate_dataset_name(name)
            except DatasetValidationError:
                self.fail(f"Valid name '{name}' was rejected")
                
    def test_validate_dataset_name_invalid(self):
        """Test invalid dataset names."""
        invalid_cases = [
            ("", "empty"),
            ("test", "reserved"),
            ("my dataset", "spaces"),
            ("!invalid", "special char"),
            ("a" * 101, "too long"),
            ("-start", "starts with hyphen")
        ]
        
        for name, reason in invalid_cases:
            with self.assertRaises(DatasetValidationError) as ctx:
                self.validator.validate_dataset_name(name)
            # Verify it failed for expected reason
            
    def test_validate_source_directory(self):
        """Test source directory validation."""
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            # Valid directory should pass
            self.validator.validate_source_directory(temp_dir)
            
            # Invalid cases
            with self.assertRaises(DatasetValidationError):
                self.validator.validate_source_directory("")
                
            with self.assertRaises(DatasetValidationError):
                self.validator.validate_source_directory("/nonexistent/path")
                
            # Create a file instead of directory
            temp_file = os.path.join(temp_dir, "file.txt")
            with open(temp_file, 'w') as f:
                f.write("test")
                
            with self.assertRaises(DatasetValidationError):
                self.validator.validate_source_directory(temp_file)


class TestWorktreeHandler(unittest.TestCase):
    """Test WorktreeHandler functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_git = Mock()
        self.handler = WorktreeHandler(self.mock_git)
        
    def test_is_worktree_true(self):
        """Test worktree detection when directory is a worktree."""
        # Mock git responses
        self.mock_git.is_git_repository.return_value = True
        self.mock_git.run_command.return_value = "/path/to/.git/worktrees/feature"
        
        # Mock .git file exists
        with patch('pathlib.Path.is_file', return_value=True):
            result = self.handler.is_worktree("/path/to/worktree")
            
        self.assertTrue(result)
        
    def test_is_worktree_false(self):
        """Test worktree detection for regular repository."""
        # Mock git responses
        self.mock_git.is_git_repository.return_value = True
        self.mock_git.run_command.return_value = "/path/to/repo/.git"
        
        # Mock .git is directory
        with patch('pathlib.Path.is_file', return_value=False):
            result = self.handler.is_worktree("/path/to/repo")
            
        self.assertFalse(result)
        
    def test_get_worktree_branch(self):
        """Test getting branch name for worktree."""
        self.mock_git.run_command.return_value = "feature-branch\n"
        
        branch = self.handler.get_worktree_branch("/path/to/worktree")
        
        self.assertEqual(branch, "feature-branch")
        
    def test_list_worktrees(self):
        """Test listing all worktrees."""
        # Mock git worktree list output
        self.mock_git.run_command.return_value = """worktree /path/to/main
HEAD abc123
branch refs/heads/main

worktree /path/to/feature
HEAD def456
branch refs/heads/feature-branch
"""
        
        worktrees = self.handler.list_worktrees("/path/to/main")
        
        self.assertEqual(len(worktrees), 2)
        self.assertEqual(worktrees[0]['path'], "/path/to/main")
        self.assertEqual(worktrees[1]['branch'], "refs/heads/feature-branch")


if __name__ == '__main__':
    unittest.main()