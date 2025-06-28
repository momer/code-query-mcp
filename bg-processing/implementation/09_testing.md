# Step 9: Testing

## Overview
Create unit tests for all major components focusing on core functionality testing.

## References
- phase1_pr_plan.md: Success Criteria
- Simplified approach: Unit tests only

## Implementation Tasks

### 9.1 Create test structure

```
tests/
├── __init__.py
├── test_worker_detection.py
├── test_queue_operations.py
├── test_config_loading.py
├── test_git_hooks.py
├── test_error_handling.py
└── fixtures/
    ├── __init__.py
    └── test_configs.py
```

### 9.2 Test worker detection (tests/test_worker_detection.py)

```python
import unittest
import tempfile
import os
import time
from unittest.mock import Mock, patch, MagicMock

from helpers.worker_detector import WorkerDetector, is_worker_running_minimal

class TestWorkerDetection(unittest.TestCase):
    """Test suite for worker detection functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
        os.makedirs(os.path.join(self.temp_dir, '.code-query'), exist_ok=True)
        self.detector = WorkerDetector(self.project_root)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_no_pid_file(self):
        """Test detection when PID file doesn't exist."""
        is_running, pid = self.detector.is_worker_running()
        self.assertFalse(is_running)
        self.assertIsNone(pid)
    
    def test_valid_pid_file(self):
        """Test detection with valid PID file."""
        # Write current process PID
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        current_pid = os.getpid()
        
        with open(pid_file, 'w') as f:
            f.write(str(current_pid))
        
        # Mock psutil to verify our process
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.cmdline.return_value = ['python', 'huey_consumer', 'tasks.huey']
            mock_process_class.return_value = mock_process
            
            with patch('psutil.pid_exists', return_value=True):
                is_running, pid = self.detector.is_worker_running()
                
                self.assertTrue(is_running)
                self.assertEqual(pid, current_pid)
    
    def test_stale_pid_file(self):
        """Test cleanup of stale PID file."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        # Write non-existent PID
        with open(pid_file, 'w') as f:
            f.write('99999')
        
        with patch('psutil.pid_exists', return_value=False):
            is_running, pid = self.detector.is_worker_running()
            
            self.assertFalse(is_running)
            self.assertIsNone(pid)
            # PID file should be cleaned up
            self.assertFalse(os.path.exists(pid_file))
    
    def test_pid_reuse(self):
        """Test detection when PID is reused by different process."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        current_pid = os.getpid()
        
        with open(pid_file, 'w') as f:
            f.write(str(current_pid))
        
        # Mock process that's NOT our worker
        with patch('psutil.Process') as mock_process_class:
            mock_process = Mock()
            mock_process.cmdline.return_value = ['some', 'other', 'process']
            mock_process_class.return_value = mock_process
            
            with patch('psutil.pid_exists', return_value=True):
                is_running, pid = self.detector.is_worker_running()
                
                self.assertFalse(is_running)
                self.assertIsNone(pid)
                # PID file should be cleaned up
                self.assertFalse(os.path.exists(pid_file))
    
    def test_corrupted_pid_file(self):
        """Test handling of corrupted PID file."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        # Write invalid content
        with open(pid_file, 'w') as f:
            f.write('not-a-number')
        
        is_running, pid = self.detector.is_worker_running()
        
        self.assertFalse(is_running)
        self.assertIsNone(pid)
        # Corrupted file should be cleaned up
        self.assertFalse(os.path.exists(pid_file))
    
    def test_minimal_detection(self):
        """Test minimal detection without psutil."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        # No PID file
        self.assertFalse(is_worker_running_minimal(self.project_root))
        
        # Valid PID (current process)
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        
        self.assertTrue(is_worker_running_minimal(self.project_root))
        
        # Invalid PID
        with open(pid_file, 'w') as f:
            f.write('99999')
        
        self.assertFalse(is_worker_running_minimal(self.project_root))

    def test_access_denied(self):
        """Test handling when process access is denied."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        with open(pid_file, 'w') as f:
            f.write('1234')
        
        with patch('psutil.pid_exists', return_value=True):
            with patch('psutil.Process') as mock_process_class:
                mock_process_class.side_effect = psutil.AccessDenied()
                
                is_running, pid = self.detector.is_worker_running()
                
                self.assertFalse(is_running)
                self.assertIsNone(pid)
```

### 9.3 Test queue operations (tests/test_queue_operations.py)

```python
import unittest
import tempfile
import os
import json
import time
from unittest.mock import patch

from storage.queue_manager import QueueManager

class TestQueueOperations(unittest.TestCase):
    """Test suite for queue management operations."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
        os.makedirs(os.path.join(self.temp_dir, '.code-query'), exist_ok=True)
        self.queue_manager = QueueManager(self.project_root)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_add_files(self):
        """Test adding files to queue."""
        files = [
            {'filepath': 'test1.py'},
            {'filepath': 'test2.py'}
        ]
        
        success = self.queue_manager.add_files(files)
        self.assertTrue(success)
        
        # Verify files were added
        snapshot = self.queue_manager.get_snapshot()
        self.assertEqual(len(snapshot), 2)
        self.assertEqual(snapshot[0]['filepath'], 'test1.py')
        self.assertTrue('timestamp' in snapshot[0])
    
    def test_remove_files(self):
        """Test removing completed files."""
        # Add files
        files = [
            {'filepath': 'test1.py'},
            {'filepath': 'test2.py'},
            {'filepath': 'test3.py'}
        ]
        self.queue_manager.add_files(files)
        
        # Remove some files
        completed = [
            {'filepath': 'test1.py'},
            {'filepath': 'test3.py'}
        ]
        removed = self.queue_manager.remove_files(completed)
        
        self.assertEqual(removed, 2)
        
        # Verify remaining files
        snapshot = self.queue_manager.get_snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['filepath'], 'test2.py')
    
    def test_duplicate_handling(self):
        """Test that duplicates are handled correctly."""
        # Add same file multiple times
        self.queue_manager.add_files([{'filepath': 'test.py'}])
        time.sleep(0.1)  # Ensure different timestamp
        self.queue_manager.add_files([{'filepath': 'test.py'}])
        
        # Should only have one entry (newest)
        snapshot = self.queue_manager.get_snapshot()
        self.assertEqual(len(snapshot), 1)
    
    def test_clear_queue(self):
        """Test clearing the queue."""
        # Add files
        files = [{'filepath': f'test{i}.py'} for i in range(5)]
        self.queue_manager.add_files(files)
        
        # Clear
        success = self.queue_manager.clear_queue()
        self.assertTrue(success)
        
        # Verify empty
        snapshot = self.queue_manager.get_snapshot()
        self.assertEqual(len(snapshot), 0)
    
    def test_atomic_operations(self):
        """Test that operations are atomic."""
        # This is a simplified test - real concurrency testing is complex
        files = [{'filepath': 'test.py'}]
        
        # Simulate concurrent add
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError("Simulated failure")
            
            success = self.queue_manager.add_files(files)
            self.assertFalse(success)
            
            # Queue should remain unchanged
            snapshot = self.queue_manager.get_snapshot()
            self.assertEqual(len(snapshot), 0)
    
    def test_queue_stats(self):
        """Test queue statistics."""
        # Add various files
        files = [
            {'filepath': 'test.py', 'timestamp': '2024-01-01T10:00:00'},
            {'filepath': 'test.js', 'timestamp': '2024-01-01T11:00:00'},
            {'filepath': 'test.py', 'timestamp': '2024-01-01T12:00:00'},
            {'filepath': 'README.md', 'timestamp': '2024-01-01T13:00:00'}
        ]
        
        for f in files:
            self.queue_manager.add_files([f])
        
        stats = self.queue_manager.get_queue_stats()
        
        self.assertEqual(stats['total_files'], 3)  # One duplicate removed
        self.assertEqual(stats['file_types']['.py'], 1)
        self.assertEqual(stats['file_types']['.js'], 1)
        self.assertEqual(stats['file_types']['.md'], 1)
        self.assertEqual(stats['oldest_timestamp'], '2024-01-01T10:00:00')
        self.assertEqual(stats['newest_timestamp'], '2024-01-01T13:00:00')
    
    def test_max_items_limit(self):
        """Test getting limited snapshot."""
        # Add many files
        files = [{'filepath': f'test{i}.py'} for i in range(10)]
        self.queue_manager.add_files(files)
        
        # Get limited snapshot
        snapshot = self.queue_manager.get_snapshot(max_items=3)
        self.assertEqual(len(snapshot), 3)
```

### 9.4 Test configuration loading (tests/test_config_loading.py)

```python
import unittest
import tempfile
import os
import json

from storage.config_manager import ConfigManager, ConfigMigrator

class TestConfigLoading(unittest.TestCase):
    """Test suite for configuration management."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, '.code-query', 'config.json')
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self.config_manager = ConfigManager(self.config_path)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_create_default_config(self):
        """Test creating default configuration."""
        self.config_manager.create_default_config()
        
        self.assertTrue(os.path.exists(self.config_path))
        
        config = self.config_manager.load_config()
        self.assertIsNotNone(config['dataset_name'])
        self.assertEqual(config['processing']['mode'], 'manual')
    
    def test_load_valid_config(self):
        """Test loading valid configuration."""
        config_data = {
            'dataset_name': 'test-project',
            'model': 'claude-3-5-sonnet-20240620',
            'processing': {
                'mode': 'auto'
            }
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(config_data, f)
        
        config = self.config_manager.load_config()
        self.assertEqual(config['dataset_name'], 'test-project')
        self.assertEqual(config['processing']['mode'], 'auto')
        # Should have defaults merged
        self.assertTrue(config['processing']['fallback_to_sync'])
    
    def test_validation_errors(self):
        """Test configuration validation."""
        # Missing required field
        with open(self.config_path, 'w') as f:
            json.dump({}, f)
        
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.load_config()
        self.assertIn('dataset_name', str(ctx.exception))
        
        # Invalid processing mode
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'processing': {'mode': 'invalid'}
            }, f)
        
        with self.assertRaises(ValueError) as ctx:
            self.config_manager.load_config()
        self.assertIn('processing mode', str(ctx.exception))
    
    def test_deep_merge(self):
        """Test deep merging of configurations."""
        # Partial config
        with open(self.config_path, 'w') as f:
            json.dump({
                'dataset_name': 'test',
                'processing': {
                    'batch_size': 10
                }
            }, f)
        
        config = self.config_manager.load_config()
        
        # Should have user value
        self.assertEqual(config['processing']['batch_size'], 10)
        # Should have defaults for missing values
        self.assertEqual(config['processing']['mode'], 'manual')
        self.assertTrue(config['processing']['fallback_to_sync'])
    
    def test_atomic_save(self):
        """Test atomic configuration saves."""
        config = {
            'dataset_name': 'test',
            'processing': {'mode': 'manual'}
        }
        
        # Mock os.replace to simulate failure
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError("Simulated failure")
            
            with self.assertRaises(OSError):
                self.config_manager.save_config(config)
        
        # Original file should be unchanged (or not exist)
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                data = f.read()
                self.assertNotIn('test', data)
    
    def test_config_migration(self):
        """Test configuration migration."""
        # Old v1 config
        old_config = {
            'dataset_name': 'test',
            'auto_process': True
        }
        
        migrated = ConfigMigrator.migrate_config(old_config)
        
        self.assertNotIn('auto_process', migrated)
        self.assertEqual(migrated['processing']['mode'], 'auto')
```

### 9.5 Test git hooks (tests/test_git_hooks.py)

```python
import unittest
import tempfile
import os
import json
from unittest.mock import Mock, patch, MagicMock

from helpers.git_hook_handler import GitHookHandler

class TestGitHooks(unittest.TestCase):
    """Test suite for git hook functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
        os.makedirs(os.path.join(self.temp_dir, '.code-query'), exist_ok=True)
        self.handler = GitHookHandler(self.project_root)
        
        # Create default config
        config = {
            'dataset_name': 'test-project',
            'processing': {'mode': 'manual'}
        }
        with open(self.handler.config_path, 'w') as f:
            json.dump(config, f)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_no_config(self):
        """Test behavior when config doesn't exist."""
        os.unlink(self.handler.config_path)
        
        exit_code = self.handler.handle_post_commit()
        self.assertEqual(exit_code, 0)  # Should not block commit
    
    def test_empty_queue(self):
        """Test behavior with empty queue."""
        # Create empty queue
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': []}, f)
        
        exit_code = self.handler.handle_post_commit()
        self.assertEqual(exit_code, 0)
    
    @patch('subprocess.run')
    def test_manual_mode_processing(self, mock_run):
        """Test synchronous processing in manual mode."""
        # Setup queue
        files = [
            {'filepath': 'test1.py', 'commit_hash': 'abc123'},
            {'filepath': 'test2.py', 'commit_hash': 'abc123'}
        ]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Mock successful subprocess
        mock_run.return_value = Mock(returncode=0, stderr='')
        
        exit_code = self.handler.handle_post_commit()
        
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_run.call_count, 2)  # Once per file
        
        # Verify queue was updated
        with open(self.handler.queue_file, 'r') as f:
            queue = json.load(f)
            self.assertEqual(len(queue['files']), 0)
    
    def test_auto_mode_no_worker(self):
        """Test auto mode when worker is not running."""
        # Update config to auto mode
        config = {
            'dataset_name': 'test-project',
            'processing': {
                'mode': 'auto',
                'fallback_to_sync': True
            }
        }
        with open(self.handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Setup queue
        files = [{'filepath': 'test.py'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Mock worker not running
        with patch.object(self.handler, '_is_worker_running', return_value=False):
            with patch.object(self.handler, '_process_synchronously') as mock_sync:
                mock_sync.return_value = 0
                
                exit_code = self.handler.handle_post_commit()
                
                self.assertEqual(exit_code, 0)
                mock_sync.assert_called_once()
    
    @patch('sys.path')
    def test_auto_mode_with_worker(self, mock_path):
        """Test auto mode when worker is running."""
        # Update config
        config = {
            'dataset_name': 'test-project',
            'processing': {'mode': 'auto'}
        }
        with open(self.handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Setup queue
        files = [{'filepath': 'test.py'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Mock worker running and Huey import
        with patch.object(self.handler, '_is_worker_running', return_value=True):
            with patch('tasks.process_file_documentation') as mock_task:
                mock_task.return_value = Mock(id='task-123')
                
                exit_code = self.handler.handle_post_commit()
                
                self.assertEqual(exit_code, 0)
                mock_task.assert_called_once()
                
                # Queue should be cleared
                with open(self.handler.queue_file, 'r') as f:
                    queue = json.load(f)
                    self.assertEqual(len(queue['files']), 0)
```

### 9.6 Test error handling (tests/test_error_handling.py)

```python
import unittest
from unittest.mock import Mock, patch
import sys

from helpers.error_handler import (
    ErrorHandler, CodeQueryError, WorkerNotRunningError,
    ConfigurationError, handle_enqueue_failure, ErrorContext
)

class TestErrorHandling(unittest.TestCase):
    """Test suite for error handling functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.handler = ErrorHandler()
    
    def test_codequery_error_handling(self):
        """Test handling of CodeQueryError instances."""
        error = WorkerNotRunningError()
        
        with patch('builtins.print') as mock_print:
            recoverable = self.handler.handle_error(error)
            
            self.assertTrue(recoverable)
            
            # Check output
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any('WARNING' in call for call in calls))
            self.assertTrue(any('suggestion' in call for call in calls))
    
    def test_critical_error_exit(self):
        """Test that critical errors cause exit."""
        error = CodeQueryError(
            "Critical failure",
            severity=ErrorSeverity.CRITICAL
        )
        
        with patch('sys.exit') as mock_exit:
            self.handler.handle_error(error, exit_on_critical=True)
            mock_exit.assert_called_once_with(1)
    
    def test_generic_error_handling(self):
        """Test handling of generic exceptions."""
        error = ValueError("Something went wrong")
        
        with patch('builtins.print') as mock_print:
            recoverable = self.handler.handle_error(error, verbose=False)
            
            self.assertFalse(recoverable)
            
            # Should not expose details without verbose
            calls = str(mock_print.call_args_list)
            self.assertNotIn("Something went wrong", calls)
            self.assertIn("--verbose", calls)
    
    def test_enqueue_failure_with_fallback(self):
        """Test enqueue failure handling with fallback."""
        error = Exception("Connection failed")
        files = [{'filepath': 'test.py'}]
        config = {'processing': {'fallback_to_sync': True}}
        
        def mock_fallback(files, config):
            return True
        
        with patch('builtins.print'):
            success = handle_enqueue_failure(
                error, files, config, mock_fallback
            )
            
            self.assertTrue(success)
    
    def test_enqueue_failure_no_fallback(self):
        """Test enqueue failure handling without fallback."""
        error = Exception("Connection failed")
        files = [{'filepath': 'test.py'}]
        config = {'processing': {'fallback_to_sync': False}}
        
        with patch('builtins.print'):
            success = handle_enqueue_failure(
                error, files, config, lambda f, c: True
            )
            
            self.assertFalse(success)
    
    def test_error_context_manager(self):
        """Test ErrorContext context manager."""
        # Test suppression
        with ErrorContext("test operation", suppress=True):
            raise CodeQueryError("Test error", recoverable=True)
        
        # Should not raise
        
        # Test no suppression
        with self.assertRaises(CodeQueryError):
            with ErrorContext("test operation", suppress=False):
                raise CodeQueryError("Test error", recoverable=True)
```

### 9.7 Create test runner

```python
# tests/run_tests.py
import unittest
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

if __name__ == '__main__':
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(__file__)
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with error code if tests failed
    sys.exit(0 if result.wasSuccessful() else 1)
```

## Testing Checklist
- [ ] Worker detection tests pass
- [ ] Queue operation tests pass
- [ ] Configuration loading tests pass
- [ ] Git hook tests pass
- [ ] Error handling tests pass
- [ ] All edge cases covered
- [ ] Mocking used appropriately
- [ ] Tests are isolated and repeatable

## Running Tests

```bash
# Run all tests
python tests/run_tests.py

# Run specific test file
python -m unittest tests.test_worker_detection

# Run with coverage
pip install coverage
coverage run tests/run_tests.py
coverage report
coverage html  # Generate HTML report
```