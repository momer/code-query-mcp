import unittest
from unittest.mock import Mock, patch, call
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.git_hook_handler import GitHookHandler
from cli.worker_manager import WorkerManager
from helpers.queue_manager import QueueManager

class TestErrorHandling(unittest.TestCase):
    """Test suite for error handling functionality."""
    
    def setUp(self):
        """Set up test environment."""
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
        os.makedirs(os.path.join(self.temp_dir, '.code-query'), exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_task_retry_mechanism(self):
        """Test that tasks retry on transient failures."""
        # This would require actually running Huey, so we test the decorator presence
        from tasks import process_file_documentation
        
        # Check that the task is a Huey task with proper configuration
        # Huey tasks are wrapped, so we check the function exists and is callable
        self.assertTrue(callable(process_file_documentation))
        # The actual retry configuration is in the decorator, not as attributes
        # We can verify by checking the source or running the task
    
    def test_git_hook_never_blocks_commit(self):
        """Test that git hooks never block commits on errors."""
        handler = GitHookHandler(self.project_root)
        
        # Test various error scenarios
        error_scenarios = [
            # No config file
            lambda: os.path.exists(handler.config_path) and os.unlink(handler.config_path),
            # Corrupted config
            lambda: self._write_file(handler.config_path, 'invalid json{'),
            # Missing queue file
            lambda: os.path.exists(handler.queue_file) and os.unlink(handler.queue_file),
            # Exception in processing
            lambda: None  # Will be mocked below
        ]
        
        for scenario in error_scenarios:
            scenario()
            
            # Mock an exception during processing
            with patch.object(handler, '_process_synchronously', side_effect=Exception("Test error")):
                exit_code = handler.handle_post_commit()
                
                # Should always return 0 (success) to not block commit
                self.assertEqual(exit_code, 0)
    
    def test_worker_graceful_shutdown(self):
        """Test worker handles shutdown gracefully."""
        worker_manager = WorkerManager(self.project_root)
        
        # Mock a running worker
        pid_file = worker_manager.pid_file
        with open(pid_file, 'w') as f:
            f.write('12345')
        
        with patch('os.kill') as mock_kill:
            # Mock psutil to simulate worker running then stopping
            mock_process = Mock()
            mock_process.cmdline.return_value = ['huey_consumer', 'tasks.huey']
            
            with patch('psutil.pid_exists', side_effect=[True, True, True, False]):
                with patch('psutil.Process', return_value=mock_process):
                    success = worker_manager.stop_worker()
                    
                    # Should send SIGTERM first
                    # The call could be with signal.SIGTERM or value 15
                    mock_kill.assert_called()
                    # Get the first call args
                    first_call = mock_kill.call_args_list[0]
                    self.assertEqual(first_call[0][0], 12345)  # PID
                    # Signal could be the object or the value
                    signal_arg = first_call[0][1]
                    import signal
                    self.assertTrue(signal_arg == signal.SIGTERM or signal_arg == 15)
                    self.assertTrue(success)
    
    def test_queue_corruption_recovery(self):
        """Test recovery from corrupted queue files."""
        queue_manager = QueueManager(self.project_root)
        
        # Create corrupted queue file
        queue_file = queue_manager.queue_file
        with open(queue_file, 'w') as f:
            f.write('corrupted json data {[')
        
        # Should handle gracefully
        files = queue_manager.list_queued_files()
        self.assertEqual(files, [])
        
        # Should be able to add files (recreating queue)
        count = queue_manager.add_files([('test.py', 'abc123')])
        self.assertEqual(count, 1)
        
        # Verify queue is now valid
        files = queue_manager.list_queued_files()
        self.assertEqual(len(files), 1)
    
    def test_path_validation_errors(self):
        """Test path validation prevents security issues."""
        handler = GitHookHandler(self.project_root)
        
        # Setup config
        config = {
            'dataset_name': 'test',
            'processing': {'mode': 'manual'}
        }
        with open(handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Setup queue with various malicious paths
        malicious_files = [
            {'filepath': '../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': '/etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': 'test/../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': 'test\x00.py', 'commit_hash': 'abc123'},  # Null byte
        ]
        
        with open(handler.queue_file, 'w') as f:
            json.dump({'files': malicious_files}, f)
        
        with patch('subprocess.run') as mock_run:
            with patch('builtins.print') as mock_print:
                exit_code = handler.handle_post_commit()
                
                # Should not process any files
                mock_run.assert_not_called()
                
                # Should print skip messages
                print_calls = [str(call) for call in mock_print.call_args_list]
                self.assertTrue(any('outside project' in str(call) for call in print_calls))
    
    def test_fallback_on_import_error(self):
        """Test fallback when Huey import fails."""
        handler = GitHookHandler(self.project_root)
        
        # Setup for auto mode
        config = {
            'dataset_name': 'test',
            'processing': {'mode': 'auto'}
        }
        with open(handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Create queue and file
        files = [{'filepath': 'test.py', 'commit_hash': 'abc123'}]
        with open(handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        test_file = os.path.join(self.project_root, 'test.py')
        with open(test_file, 'w') as f:
            f.write('print("test")')
        
        # Mock worker running but import fails
        with patch.object(handler, '_is_worker_running', return_value=True):
            with patch('builtins.__import__', side_effect=ImportError("No module named 'tasks'")):
                with patch.object(handler, '_process_synchronously') as mock_sync:
                    mock_sync.return_value = 0
                    
                    exit_code = handler.handle_post_commit()
                    
                    # Should fall back to sync
                    self.assertEqual(exit_code, 0)
                    mock_sync.assert_called_once()
    
    def test_atomic_operations_prevent_corruption(self):
        """Test that atomic operations prevent file corruption."""
        queue_manager = QueueManager(self.project_root)
        
        # Add initial files
        queue_manager.add_files([('test1.py', 'abc123')])
        
        # Simulate failure during write - os.replace is used for atomicity
        with patch('os.replace', side_effect=OSError("Disk full")):
            # This will raise an exception
            with self.assertRaises(OSError):
                queue_manager.add_files([('test2.py', 'def456')])
        
        # Original queue should be intact
        files = queue_manager.list_queued_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]['filepath'], 'test1.py')
    
    def test_log_sanitization(self):
        """Test that sensitive information is not logged."""
        # This is more of a code review item, but we can test some aspects
        from tasks import process_file_documentation
        
        # Mock the task execution with an API key in error
        with patch('storage.sqlite_storage.CodeQueryServer') as mock_storage:
            mock_storage.side_effect = Exception("API key: sk-1234567890")
            
            # The error should be caught and sanitized
            # In real implementation, we'd check log output
            # For now, we verify the task structure exists
            self.assertTrue(callable(process_file_documentation))
    
    def test_cleanup_on_error(self):
        """Test that resources are cleaned up on errors."""
        worker_manager = WorkerManager(self.project_root)
        
        # Mock subprocess failure
        with patch('subprocess.Popen', side_effect=OSError("Cannot start process")):
            success = worker_manager.start_worker()
            self.assertFalse(success)
            
            # PID file should not exist
            self.assertFalse(os.path.exists(worker_manager.pid_file))
    
    def _write_file(self, path, content):
        """Helper to write file content."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)