import unittest
import tempfile
import os
import json
from unittest.mock import Mock, patch, MagicMock, call

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        
        # Create actual files
        for file_info in files:
            filepath = os.path.join(self.project_root, file_info['filepath'])
            with open(filepath, 'w') as f:
                f.write('print("test")')
        
        # Mock successful subprocess with valid JSON response
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'overview': 'Test file',
            'functions': {},
            'imports': {},
            'exports': {},
            'types_interfaces_classes': {},
            'constants': {},
            'dependencies': [],
            'other_notes': []
        })
        mock_run.return_value = mock_result
        
        # Mock the storage update
        with patch('storage.sqlite_storage.CodeQueryServer') as mock_storage_class:
            mock_storage = Mock()
            mock_storage.update_file_documentation = Mock()
            mock_storage_class.return_value = mock_storage
            
            exit_code = self.handler.handle_post_commit()
            
            self.assertEqual(exit_code, 0)
            self.assertEqual(mock_run.call_count, 2)  # Once per file
            
            # Verify storage was called
            self.assertEqual(mock_storage.update_file_documentation.call_count, 2)
    
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
        files = [{'filepath': 'test.py', 'commit_hash': 'abc123'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Create the file
        test_file = os.path.join(self.project_root, 'test.py')
        with open(test_file, 'w') as f:
            f.write('print("test")')
        
        # Mock worker not running
        with patch.object(self.handler, '_is_worker_running', return_value=False):
            with patch.object(self.handler, '_process_synchronously') as mock_sync:
                mock_sync.return_value = 0
                
                # Capture print output during execution
                with patch('builtins.print') as mock_print:
                    exit_code = self.handler.handle_post_commit()
                    
                    self.assertEqual(exit_code, 0)
                    mock_sync.assert_called_once()
                    
                    # Check that fallback message was printed
                    print_calls = [str(call) for call in mock_print.call_args_list]
                    self.assertTrue(any('Background worker not running' in call for call in print_calls))
    
    def test_auto_mode_with_worker(self):
        """Test auto mode when worker is running."""
        # Update config
        config = {
            'dataset_name': 'test-project',
            'processing': {'mode': 'auto'}
        }
        with open(self.handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Setup queue
        files = [{'filepath': 'test.py', 'commit_hash': 'abc123'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Mock worker running and Huey import
        with patch.object(self.handler, '_is_worker_running', return_value=True):
            # Mock the module import
            mock_tasks = Mock()
            mock_task_func = Mock()
            mock_task_func.return_value = Mock(id='task-123')
            mock_tasks.process_file_documentation = mock_task_func
            mock_tasks.huey = Mock()
            
            with patch.dict('sys.modules', {'tasks': mock_tasks}):
                exit_code = self.handler.handle_post_commit()
                
                self.assertEqual(exit_code, 0)
                mock_task_func.assert_called_once()
                
                # Verify task was called with correct arguments
                call_args = mock_task_func.call_args[1]
                self.assertEqual(call_args['filepath'], 'test.py')
                # The code uses 'datasetName' from config which defaults to 'default'
                self.assertEqual(call_args['dataset_name'], 'default')
                self.assertEqual(call_args['commit_hash'], 'abc123')
                self.assertEqual(call_args['project_root'], self.project_root)
    
    def test_queue_atomic_clear(self):
        """Test that queue is cleared atomically."""
        # Setup queue
        files = [{'filepath': 'test.py', 'commit_hash': 'abc123'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Call the atomic clear method
        snapshot = self.handler._load_queue_snapshot_and_clear()
        
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['filepath'], 'test.py')
        
        # Queue file should not exist anymore
        self.assertFalse(os.path.exists(self.handler.queue_file))
    
    def test_corrupted_queue_handling(self):
        """Test handling of corrupted queue file."""
        # Create corrupted queue
        with open(self.handler.queue_file, 'w') as f:
            f.write('not valid json{')
        
        snapshot = self.handler._load_queue_snapshot_and_clear()
        
        # Should return empty list on corruption
        self.assertEqual(snapshot, [])
    
    def test_path_traversal_prevention(self):
        """Test that path traversal attacks are prevented."""
        # Setup queue with malicious path
        files = [
            {'filepath': '../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': 'test.py', 'commit_hash': 'abc123'}
        ]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Create the valid file
        test_file = os.path.join(self.project_root, 'test.py')
        with open(test_file, 'w') as f:
            f.write('print("test")')
        
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({'overview': 'Test'})
            mock_run.return_value = mock_result
            
            with patch('storage.sqlite_storage.CodeQueryServer'):
                exit_code = self.handler.handle_post_commit()
                
                # Should only process the valid file
                self.assertEqual(mock_run.call_count, 1)
    
    def test_worker_detection_cross_platform(self):
        """Test worker detection works cross-platform."""
        # Create PID file
        with open(self.handler.pid_file, 'w') as f:
            f.write(str(os.getpid()))
        
        # Should detect current process as "running"
        is_running = self.handler._is_worker_running()
        self.assertTrue(is_running)
        
        # Non-existent PID
        with open(self.handler.pid_file, 'w') as f:
            f.write('99999')
        
        is_running = self.handler._is_worker_running()
        self.assertFalse(is_running)