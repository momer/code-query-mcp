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
                # The code now handles both 'datasetName' and 'dataset_name'
                self.assertEqual(call_args['dataset_name'], 'test-project')
                self.assertEqual(call_args['commit_hash'], 'abc123')
                self.assertEqual(call_args['project_root'], self.project_root)
    
    def test_auto_mode_with_main_dataset_name_config(self):
        """Test auto mode with mainDatasetName config field (used by create_project_config)."""
        # Update config to use mainDatasetName (as created by create_project_config)
        config = {
            'mainDatasetName': 'main-project-name',
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
                # Should use mainDatasetName from config
                self.assertEqual(call_args['dataset_name'], 'main-project-name')
                self.assertEqual(call_args['commit_hash'], 'abc123')
                self.assertEqual(call_args['project_root'], self.project_root)
    
    def test_queue_load_and_clear_sequential(self):
        """Test that queue is loaded and cleared in sequential operation."""
        # Setup queue
        files = [{'filepath': 'test.py', 'commit_hash': 'abc123'}]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Call the load and clear method
        snapshot = self.handler._load_queue_snapshot_and_clear()
        
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['filepath'], 'test.py')
        
        # Queue file should not exist anymore
        self.assertFalse(os.path.exists(self.handler.queue_file))
    
    def test_queue_atomic_clear_under_concurrency(self):
        """Test that queue clearing is truly atomic under concurrent access."""
        import threading
        import time
        
        # Results storage for concurrent operations
        results = {
            'snapshots': [],
            'exceptions': [],
            'file_exists_during': [],
            'stop_writing': threading.Event()
        }
        
        # Lock for thread-safe result collection
        results_lock = threading.Lock()
        
        def write_to_queue():
            """Continuously write to queue file to simulate concurrent updates."""
            for i in range(50):
                if results['stop_writing'].is_set():
                    break
                try:
                    # Try to write new data to queue
                    new_data = {'files': [{'filepath': f'concurrent_{i}.py', 'commit_hash': f'hash_{i}'}]}
                    with open(self.handler.queue_file, 'w') as f:
                        json.dump(new_data, f)
                    time.sleep(0.001)  # Small delay to allow interleaving
                except Exception as e:
                    with results_lock:
                        results['exceptions'].append(('write', str(e)))
        
        def read_and_clear_queue():
            """Attempt to read and clear queue atomically."""
            time.sleep(0.005)  # Small delay to ensure writer starts first
            try:
                snapshot = self.handler._load_queue_snapshot_and_clear()
                with results_lock:
                    results['snapshots'].append(snapshot)
                # Signal writer to stop after atomic operation completes
                results['stop_writing'].set()
            except Exception as e:
                with results_lock:
                    results['exceptions'].append(('read_clear', str(e)))
        
        def check_file_existence():
            """Monitor file existence during operations."""
            for _ in range(100):
                exists = os.path.exists(self.handler.queue_file)
                with results_lock:
                    results['file_exists_during'].append(exists)
                time.sleep(0.001)
        
        # Initial queue setup
        initial_data = {'files': [{'filepath': 'initial.py', 'commit_hash': 'initial_hash'}]}
        with open(self.handler.queue_file, 'w') as f:
            json.dump(initial_data, f)
        
        # Create threads for concurrent operations
        writer_thread = threading.Thread(target=write_to_queue)
        reader_thread = threading.Thread(target=read_and_clear_queue)
        monitor_thread = threading.Thread(target=check_file_existence)
        
        # Start all threads
        writer_thread.start()
        reader_thread.start()
        monitor_thread.start()
        
        # Wait for completion
        writer_thread.join()
        reader_thread.join()
        monitor_thread.join()
        
        # Verify atomicity properties:
        # 1. Exactly one snapshot should be captured (no partial reads)
        self.assertEqual(len(results['snapshots']), 1, 
                        "Should capture exactly one snapshot atomically")
        
        # 2. The snapshot should contain valid data (not corrupted)
        snapshot = results['snapshots'][0]
        self.assertIsInstance(snapshot, list, "Snapshot should be a list")
        if snapshot:  # Could be empty if cleared before any writes
            self.assertTrue(all('filepath' in item and 'commit_hash' in item for item in snapshot),
                           "All items in snapshot should have required fields")
        
        # 3. No unexpected exceptions during concurrent operations
        # We expect some FileNotFoundError when writer tries to write after atomic clear
        unexpected_errors = []
        for op, error in results['exceptions']:
            if op == 'write' and '[Errno 2]' in error:
                # Expected - file was atomically moved
                continue
            if op == 'read_clear' and 'FileNotFoundError' in error:
                # Could happen if multiple readers race
                continue
            unexpected_errors.append((op, error))
        
        self.assertEqual(len(unexpected_errors), 0, 
                        f"No unexpected errors should occur: {unexpected_errors}")
        
        # 4. Verify atomic behavior in file existence monitoring
        # The file should transition from existing to not existing
        if results['file_exists_during']:
            # Find the first transition point where file disappeared
            transition_found = False
            for i in range(1, len(results['file_exists_during'])):
                if results['file_exists_during'][i-1] and not results['file_exists_during'][i]:
                    transition_found = True
                    break
            
            self.assertTrue(transition_found, 
                           "File should have transitioned from existing to not existing")
        
        # 5. Clean up any file that might have been created after stop signal
        if os.path.exists(self.handler.queue_file):
            os.remove(self.handler.queue_file)
    
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
        # Setup queue with various malicious paths
        files = [
            {'filepath': '../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': '/etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': '..\\..\\..\\windows\\system32\\config\\sam', 'commit_hash': 'abc123'},
            {'filepath': 'test/../../../etc/shadow', 'commit_hash': 'abc123'},
            {'filepath': './safe.py', 'commit_hash': 'abc123'},
            {'filepath': 'subdir/safe2.py', 'commit_hash': 'abc123'}
        ]
        with open(self.handler.queue_file, 'w') as f:
            json.dump({'files': files}, f)
        
        # Create the valid files
        safe_file = os.path.join(self.project_root, 'safe.py')
        with open(safe_file, 'w') as f:
            f.write('print("safe")')
        
        subdir = os.path.join(self.project_root, 'subdir')
        os.makedirs(subdir, exist_ok=True)
        safe2_file = os.path.join(subdir, 'safe2.py')
        with open(safe2_file, 'w') as f:
            f.write('print("safe2")')
        
        with patch('subprocess.run') as mock_run:
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
            
            with patch('storage.sqlite_storage.CodeQueryServer') as mock_storage_class:
                mock_storage = Mock()
                mock_storage.update_file_documentation = Mock()
                mock_storage_class.return_value = mock_storage
                
                # Capture print output to verify which files were skipped
                with patch('builtins.print') as mock_print:
                    exit_code = self.handler.handle_post_commit()
                
                    # Verify only safe files were processed successfully
                    # Note: After removing TOCTOU check, some malicious files may reach the open() stage
                    # before failing, but they won't be successfully processed (counted in completions)
                    self.assertEqual(mock_run.call_count, 2)  # Only safe.py and subdir/safe2.py succeed
                    
                    # CRITICAL: Verify the exact files that were processed by checking ALL subprocess arguments
                    processed_files = []
                    all_subprocess_args = []
                    
                    for call_obj in mock_run.call_args_list:
                        # Get the full command line arguments
                        cmd_args = call_obj[0][0]  # First positional argument to subprocess.run
                        all_subprocess_args.append(cmd_args)
                        
                        # Verify the command structure
                        self.assertEqual(cmd_args[0], 'claude')
                        self.assertEqual(cmd_args[1], '-p')
                        # cmd_args[2] is the prompt
                        # cmd_args[3] is '--model'
                        # cmd_args[4] is the model name
                        
                        # Extract the actual file path from the prompt (3rd argument)
                        prompt = cmd_args[2]
                        
                        # Use a more robust extraction that handles the exact prompt format
                        # The prompt should contain "File: <filepath>\n"
                        import re
                        match = re.search(r'File: (.+?)\n', prompt)
                        if match:
                            filepath = match.group(1)
                            processed_files.append(filepath)
                            
                            # CRITICAL: Verify the file path is safe and within project
                            # Use realpath to match the implementation and handle symlinks
                            resolved_filepath = os.path.realpath(os.path.join(self.project_root, filepath))
                            real_project_root = os.path.realpath(self.project_root)
                            
                            # Ensure the resolved path is within the project root
                            self.assertTrue(
                                resolved_filepath.startswith(real_project_root),
                                f"File {filepath} resolves outside project root: {resolved_filepath}"
                            )
                            
                            # Ensure no parent directory references in the resolved path
                            self.assertNotIn('..', resolved_filepath)
                    
                    # Assert EXACTLY which files were processed
                    self.assertEqual(sorted(processed_files), sorted(['./safe.py', 'subdir/safe2.py']),
                                   f"Expected only safe files to be processed, but got: {processed_files}")
                    
                    # Verify malicious paths were NEVER passed to subprocess in ANY form
                    all_subprocess_text = str(all_subprocess_args)
                    
                    # Check for various malicious patterns
                    self.assertNotIn('/etc/passwd', all_subprocess_text)
                    self.assertNotIn('etc/passwd', all_subprocess_text)  # Even without leading slash
                    self.assertNotIn('../..', all_subprocess_text)
                    self.assertNotIn('..\\\\..', all_subprocess_text)
                    self.assertNotIn('windows\\system32', all_subprocess_text)
                    self.assertNotIn('windows\\\\system32', all_subprocess_text)
                    self.assertNotIn('/etc/shadow', all_subprocess_text)
                    self.assertNotIn('etc/shadow', all_subprocess_text)
                    
                    # Verify print output shows ALL malicious files were skipped with correct reasons
                    print_calls = [str(call) for call in mock_print.call_args_list]
                    print_output = ' '.join(print_calls)
                    
                    # Check each malicious file was reported as skipped
                    self.assertIn('Skipping ../../../etc/passwd (outside project)', print_output)
                    self.assertIn('Skipping /etc/passwd (outside project)', print_output)
                    self.assertIn('Skipping test/../../../etc/shadow (outside project)', print_output)
                    
                    # The Windows path might be reported differently based on platform
                    # On Linux, backslashes aren't treated as path separators, so the Windows path
                    # may reach the open() stage before failing (which is fine - it still fails)
                    windows_path_handled = (
                        'Skipping ..\\..\\..\\windows\\system32\\config\\sam (outside project)' in print_output or
                        'Skipping ..\\\\..\\\\..\\\\windows\\\\system32\\\\config\\\\sam (not a file)' in print_output or
                        'Skipping ..\\\\..\\\\..\\\\windows\\\\system32\\\\config\\\\sam (outside project)' in print_output or
                        'No such file or directory' in print_output  # Failed at open() stage, which is secure
                    )
                    self.assertTrue(windows_path_handled, 
                                  f"Windows malicious path not properly handled in output: {print_output}")
                    
                    # Verify storage was called only for safe files
                    self.assertEqual(mock_storage.update_file_documentation.call_count, 2)
                    storage_calls = mock_storage.update_file_documentation.call_args_list
                    stored_files = [call[1]['filepath'] for call in storage_calls]
                    self.assertEqual(sorted(stored_files), sorted(['./safe.py', 'subdir/safe2.py']),
                                   "Storage should only be called for safe files")
    
    def test_worker_detection_basic_functionality(self):
        """Test worker detection basic functionality with valid and invalid PIDs."""
        # Test with current process PID (should be detected as running)
        with open(self.handler.pid_file, 'w') as f:
            f.write(str(os.getpid()))
        
        # Should detect current process as "running"
        is_running = self.handler._is_worker_running()
        self.assertTrue(is_running)
        
        # Test with non-existent PID (should not be detected)
        with open(self.handler.pid_file, 'w') as f:
            f.write('99999')
        
        is_running = self.handler._is_worker_running()
        self.assertFalse(is_running)