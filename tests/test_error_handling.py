import unittest
from unittest.mock import Mock, patch, call
import sys
import os
import json
import tempfile
import logging

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
        """Test that tasks retry on transient failures but not on validation errors."""
        from tasks import process_file_documentation, huey
        
        # Test 1: Verify retry configuration
        # Check that process_file_documentation is decorated as a Huey task
        self.assertTrue(hasattr(process_file_documentation, 'call_local'), 
                       "process_file_documentation should be a Huey task (has call_local method)")
        
        # Verify retry configuration matches what's in the decorator
        self.assertEqual(process_file_documentation.settings['default_retries'], 2, 
                        "Task should have retries=2 as configured in @huey.task decorator")
        self.assertEqual(process_file_documentation.settings['default_retry_delay'], 60, 
                        "Task should have retry_delay=60 as configured in @huey.task decorator")
        
        # Setup test environment
        test_filepath = 'test.py'
        test_dataset = 'test_dataset'
        test_commit = 'abc123'
        test_project_root = self.temp_dir
        
        # Create test file
        test_file_path = os.path.join(test_project_root, test_filepath)
        with open(test_file_path, 'w') as f:
            f.write('# Test file content\nprint("Hello world")')
        
        # Create config file
        config_path = os.path.join(test_project_root, '.code-query', 'config.json')
        with open(config_path, 'w') as f:
            json.dump({'model': 'test-model'}, f)
        
        # Test 2: Verify non-retriable errors (validation phase) don't trigger retries
        # These errors should return immediately without raising exceptions
        
        # Test 2a: Security violation (path traversal)
        malicious_filepath = '../../../etc/passwd'
        result = process_file_documentation.call_local(
            filepath=malicious_filepath,
            dataset_name=test_dataset,
            commit_hash=test_commit,
            project_root=test_project_root
        )
        
        # Should fail immediately without retries
        self.assertFalse(result['success'])
        self.assertIn('Security violation', result['error'])
        
        # Test 2b: File not found
        result = process_file_documentation.call_local(
            filepath='nonexistent.py',
            dataset_name=test_dataset,
            commit_hash=test_commit,
            project_root=test_project_root
        )
        
        # Should fail immediately without retries
        self.assertFalse(result['success'])
        self.assertIn('File not found', result['error'])
        
        # Test 2c: Missing configuration
        # Temporarily remove config file
        os.unlink(config_path)
        result = process_file_documentation.call_local(
            filepath=test_filepath,
            dataset_name=test_dataset,
            commit_hash=test_commit,
            project_root=test_project_root
        )
        
        # Should fail immediately without retries
        self.assertFalse(result['success'])
        self.assertIn('Validation failed', result['error'])
        
        # Restore config for next tests
        with open(config_path, 'w') as f:
            json.dump({'model': 'test-model'}, f)
        
        # Test 3: Verify retriable errors (execution phase) would trigger retries
        # These errors should raise exceptions that Huey would retry
        
        # Test 3a: Claude API failure (network/transient error)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1, 
                stderr="Network connection error",
                stdout=""
            )
            
            with patch('tasks.get_storage_server') as mock_get_storage:
                mock_instance = Mock()
                mock_get_storage.return_value = mock_instance
                
                # This should raise an exception (which Huey would retry)
                with self.assertRaises(Exception) as cm:
                    result = process_file_documentation.call_local(
                        filepath=test_filepath,
                        dataset_name=test_dataset,
                        commit_hash=test_commit,
                        project_root=test_project_root
                    )
                
                # Verify the exception message indicates a retriable error
                self.assertIn("Claude processing failed", str(cm.exception))
                
                # Verify subprocess was called (reached the retriable phase)
                mock_run.assert_called_once()
        
        # Test 3b: File read error after validation (retriable)
        # Simulate a file that becomes unreadable after validation
        with patch('builtins.open') as mock_open:
            # Configure the mock to succeed for config reads but fail for file content read
            def side_effect(file, *args, **kwargs):
                if '.code-query/config.json' in str(file):
                    # Return actual config file
                    return open(config_path, *args, **kwargs)
                elif str(file) == test_file_path and 'r' in str(args):
                    # Fail when trying to read the actual file content
                    raise IOError("Disk read error")
                else:
                    # For other operations, return a mock file object
                    mock_file = Mock()
                    mock_file.__enter__ = Mock(return_value=mock_file)
                    mock_file.__exit__ = Mock(return_value=None)
                    mock_file.read = Mock(return_value='# Test content')
                    return mock_file
            
            mock_open.side_effect = side_effect
            
            # Also need to ensure os.path.isfile returns True
            with patch('os.path.isfile', return_value=True):
                # This should raise an exception (which Huey would retry)
                with self.assertRaises(IOError) as cm:
                    result = process_file_documentation.call_local(
                        filepath=test_filepath,
                        dataset_name=test_dataset,
                        commit_hash=test_commit,
                        project_root=test_project_root
                    )
                
                self.assertIn("Disk read error", str(cm.exception))
        
        # Test 3c: Database update failure (retriable)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Documentation output",
                stderr=""
            )
            
            with patch('tasks.get_storage_server') as mock_storage:
                # Simulate database connection error
                mock_storage.side_effect = Exception("Database connection lost")
                
                # This should raise an exception (which Huey would retry)
                with self.assertRaises(Exception) as cm:
                    result = process_file_documentation.call_local(
                        filepath=test_filepath,
                        dataset_name=test_dataset,
                        commit_hash=test_commit,
                        project_root=test_project_root
                    )
                
                self.assertIn("Database connection lost", str(cm.exception))
        
        # Test 4: Verify successful execution
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Documentation output",
                stderr=""
            )
            
            with patch('tasks.get_storage_server') as mock_get_storage:
                mock_instance = Mock()
                mock_get_storage.return_value = mock_instance
                
                result = process_file_documentation.call_local(
                    filepath=test_filepath,
                    dataset_name=test_dataset,
                    commit_hash=test_commit,
                    project_root=test_project_root
                )
                
                # Should succeed
                self.assertTrue(result['success'])
                self.assertEqual(result['filepath'], test_filepath)
                
                # Verify database update was called
                mock_instance.update_file_documentation.assert_called_once()
                
                # Verify the call had the right parameters
                call_args = mock_instance.update_file_documentation.call_args
                self.assertEqual(call_args.kwargs['dataset_name'], test_dataset)
                self.assertEqual(call_args.kwargs['filepath'], test_filepath)
                self.assertEqual(call_args.kwargs['commit_hash'], test_commit)
    
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
            'datasetName': 'test',
            'processing': {'mode': 'manual'}
        }
        with open(handler.config_path, 'w') as f:
            json.dump(config, f)
        
        # Setup queue with various malicious paths
        # Each path tests a different attack vector
        malicious_files = [
            # Directory traversal attacks (these WILL be caught on Linux)
            {'filepath': '../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': 'test/../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': './test/../../../../../../etc/passwd', 'commit_hash': 'abc123'},
            
            # Absolute paths (these WILL be caught)
            {'filepath': '/etc/passwd', 'commit_hash': 'abc123'},
            
            # Symlink-like paths (these WILL be caught)
            {'filepath': './symlink/../../../etc/passwd', 'commit_hash': 'abc123'},
            {'filepath': 'test/./../.././../../etc/passwd', 'commit_hash': 'abc123'},
        ]
        
        # Platform-specific paths that may or may not be caught depending on OS
        platform_specific_files = []
        if os.name == 'nt':  # Windows
            platform_specific_files.extend([
                # Windows style paths (caught on Windows, not on Linux)
                {'filepath': '..\\..\\..\\etc\\passwd', 'commit_hash': 'abc123'},
                {'filepath': 'C:\\Windows\\System32\\config\\sam', 'commit_hash': 'abc123'},
                {'filepath': '..\\..\\.\\Windows\\System32\\drivers\\etc\\hosts', 'commit_hash': 'abc123'},
                {'filepath': 'C:/Windows/System32/drivers/etc/hosts', 'commit_hash': 'abc123'},
            ])
        
        # Paths that require special handling/decoding (may not be caught by basic path validation)
        potentially_uncaught_files = [
            # Null byte injection (may not be caught if not specifically handled)
            {'filepath': 'test.py\x00.txt', 'commit_hash': 'abc123'},
            {'filepath': 'test\x00/../../../etc/passwd', 'commit_hash': 'abc123'},
            
            # URL encoded paths (may not be caught if not decoded)
            {'filepath': '..%2F..%2F..%2Fetc%2Fpasswd', 'commit_hash': 'abc123'},
            {'filepath': '%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd', 'commit_hash': 'abc123'},
            
            # Double encoding (may not be caught if not decoded)
            {'filepath': '..%252F..%252F..%252Fetc%252Fpasswd', 'commit_hash': 'abc123'},
            
            # Unicode normalization attacks (may not be caught if not normalized)
            {'filepath': '..／..／..／etc／passwd', 'commit_hash': 'abc123'},  # Unicode slash U+FF0F
            
            # Mixed encoding attacks (may not be caught if not decoded)
            {'filepath': '..%5c..%5c..%5cetc%5cpasswd', 'commit_hash': 'abc123'},  # URL encoded backslashes
            {'filepath': '%2e%2e%5c%2e%2e%5c%2e%2e%5cetc%5cpasswd', 'commit_hash': 'abc123'},
        ]
        
        # On Linux, Windows-style backslashes are treated as literal characters, not path separators
        # So they won't actually traverse directories and may not be caught by the current validation
        if os.name != 'nt':  # Not Windows
            potentially_uncaught_files.extend([
                {'filepath': '..\\..\\..\\etc\\passwd', 'commit_hash': 'abc123'},
                {'filepath': 'C:\\Windows\\System32\\config\\sam', 'commit_hash': 'abc123'},
                {'filepath': '..\\..\\.\\Windows\\System32\\drivers\\etc\\hosts', 'commit_hash': 'abc123'},
            ])
        
        # Combine all files for testing
        all_malicious_files = malicious_files + platform_specific_files
        
        # These are the files we EXPECT to be rejected by the current validation
        expected_rejected_files = malicious_files + platform_specific_files
        
        # Also test some valid files to ensure we're not over-blocking
        valid_file = os.path.join(self.project_root, 'valid_test.py')
        with open(valid_file, 'w') as f:
            f.write('# Valid test file')
        
        # Test with all files including potentially uncaught ones
        all_test_files = all_malicious_files + potentially_uncaught_files + [{'filepath': 'valid_test.py', 'commit_hash': 'abc123'}]
        
        with open(handler.queue_file, 'w') as f:
            json.dump({'files': all_test_files}, f)
        
        # Track which paths were rejected and which were processed
        rejected_paths = set()
        subprocess_calls = []
        processed_paths = set()
        
        def mock_subprocess_run(*args, **kwargs):
            """Track subprocess calls - should never be called with malicious paths"""
            subprocess_calls.append((args, kwargs))
            # Return success for valid files with proper JSON response
            json_response = '''
            {
                "overview": "Test file overview",
                "functions": {},
                "imports": {},
                "exports": {},
                "types_interfaces_classes": {},
                "constants": {},
                "dependencies": [],
                "other_notes": []
            }
            '''
            return Mock(returncode=0, stdout=json_response.strip())
        
        with patch('subprocess.run', side_effect=mock_subprocess_run) as mock_run:
            with patch('builtins.print') as mock_print:
                with patch('storage.sqlite_storage.CodeQueryServer') as mock_storage:
                    exit_code = handler.handle_post_commit()
                    
                    # Should always return 0 to not block commits
                    self.assertEqual(exit_code, 0)
                
                    # Analyze print calls to categorize file handling
                    for call in mock_print.call_args_list:
                        call_str = str(call)
                        
                        # Extract filepath from skip messages
                        for test_file in all_test_files:
                            filepath = test_file['filepath']
                            if filepath in call_str:
                                if 'outside project' in call_str or 'not a file' in call_str:
                                    rejected_paths.add(filepath)
                                elif 'Processing' in call_str:
                                    processed_paths.add(filepath)
                    
                    # CRITICAL: Verify ALL expected malicious paths were rejected
                    for malicious_file in expected_rejected_files:
                        filepath = malicious_file['filepath']
                        self.assertIn(filepath, rejected_paths, 
                            f"SECURITY FAILURE: Expected malicious path '{filepath}' was NOT rejected! This is a critical vulnerability.")
                    
                    # CRITICAL: Ensure subprocess.run was NEVER called with any malicious paths
                    for args, kwargs in subprocess_calls:
                        if args and len(args) > 0:
                            cmd = args[0]
                            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)
                            
                            # Check that no expected malicious path appears in the command
                            for malicious_file in expected_rejected_files:
                                filepath = malicious_file['filepath']
                                self.assertNotIn(filepath, cmd_str,
                                    f"SECURITY FAILURE: Expected malicious path '{filepath}' was passed to subprocess! This is a critical vulnerability.")
                            
                            # Also check potentially uncaught files - if they made it to subprocess, that's also bad
                            for potentially_bad_file in potentially_uncaught_files:
                                filepath = potentially_bad_file['filepath']
                                if filepath in cmd_str:
                                    # This indicates a potential vulnerability - the validation didn't catch this path
                                    print(f"WARNING: Potentially malicious path '{filepath}' was processed. This may indicate incomplete validation.")
                    
                    # Debug: Print what happened
                    print(f"\nDEBUG: subprocess_calls: {len(subprocess_calls)}")
                    for i, (args, kwargs) in enumerate(subprocess_calls):
                        print(f"  Call {i}: args={args}, kwargs={kwargs}")
                    
                    print(f"DEBUG: rejected_paths: {rejected_paths}")
                    print(f"DEBUG: processed_paths: {processed_paths}")
                    
                    print("DEBUG: Print calls:")
                    for call in mock_print.call_args_list:
                        print(f"  {call}")
                    
                    # The valid file should have been processed
                    valid_file_processed = False
                    for args, kwargs in subprocess_calls:
                        if args and len(args) > 0:
                            cmd = args[0]
                            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)
                            if 'valid_test.py' in cmd_str:
                                valid_file_processed = True
                                break
                    
                    self.assertTrue(valid_file_processed, 
                        "Valid file 'valid_test.py' should have been processed via subprocess")
                    
                    # Verify that all subprocess calls are for legitimate files
                    legitimate_paths = {'valid_test.py'}
                    for args, kwargs in subprocess_calls:
                        if args and len(args) > 0:
                            cmd = args[0]
                            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)
                            
                            # Extract the filepath from the command
                            found_legitimate = False
                            for legit_path in legitimate_paths:
                                if legit_path in cmd_str:
                                    found_legitimate = True
                                    break
                            
                            if not found_legitimate:
                                self.fail(f"Subprocess was called with unexpected command: {cmd_str}")
                    
                    # Report on potentially uncaught files for visibility
                    uncaught_but_processed = []
                    for potentially_bad_file in potentially_uncaught_files:
                        filepath = potentially_bad_file['filepath']
                        if filepath not in rejected_paths:
                            # Check if it was processed
                            was_processed = any(filepath in str(call[0]) if call[0] else False 
                                              for call in subprocess_calls)
                            if was_processed:
                                uncaught_but_processed.append(filepath)
                    
                    if uncaught_but_processed:
                        print(f"WARNING: The following potentially malicious paths were not caught by validation: {uncaught_but_processed}")
                        print("This may indicate the need for additional validation such as URL decoding, Unicode normalization, or null byte filtering.")
    
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
        """Test that sensitive information is properly sanitized from logs."""
        import logging
        import tempfile
        from tasks import process_file_documentation, setup_logging
        
        # Create a custom logging handler to capture all log records
        class LogCapture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records = []
                self.messages = []
            
            def emit(self, record):
                self.records.append(record)
                self.messages.append(self.format(record))
        
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log') as temp_log:
            log_file_path = temp_log.name
        
        try:
            # Set up logging configuration
            setup_logging(log_file_path)
            
            # Create our capture handler with same formatting
            log_capture = LogCapture()
            log_capture.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            
            # Get the tasks logger and configure it
            tasks_logger = logging.getLogger('code-query.tasks')
            original_level = tasks_logger.level
            original_handlers = list(tasks_logger.handlers)
            
            # Set to DEBUG to capture all log levels
            tasks_logger.setLevel(logging.DEBUG)
            tasks_logger.addHandler(log_capture)
            
            # Define sensitive data patterns to test
            sensitive_data = {
                'api_keys': [
                    ('sk-1234567890abcdef', 'OpenAI API key'),
                    ('sk-proj-abcdefghijklmnop', 'OpenAI project key'),
                    ('claude-api-key-12345', 'Claude API key'),
                ],
                'tokens': [
                    ('ghp_1234567890abcdefghijklmnopqrstuvwxyz', 'GitHub personal access token'),
                    ('ghs_abcdefghijklmnopqrstuvwxyz123456', 'GitHub server token'),
                    ('npm_1234567890abcdefghijklmnop', 'NPM token'),
                ],
                'passwords': [
                    ('super_secret_password_123', 'Database password'),
                    ('MyP@ssw0rd!', 'User password'),
                    ('admin:password123', 'Basic auth credentials'),
                ],
                'secrets': [
                    ('AKIA1234567890ABCDEF', 'AWS access key'),
                    ('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY', 'AWS secret key'),
                    ('mongodb+srv://user:pass@cluster.mongodb.net', 'MongoDB connection string'),
                ]
            }
            
            # Prepare test environment
            test_file = os.path.join(self.project_root, 'test_sensitive.py')
            with open(test_file, 'w') as f:
                f.write('# Test file for log sanitization\nprint("Hello, World!")')
            
            config_path = os.path.join(self.project_root, '.code-query', 'config.json')
            with open(config_path, 'w') as f:
                json.dump({'model': 'claude-3-5-sonnet-20240620'}, f)
            
            # Test 1: Subprocess errors with sensitive data
            for category, items in sensitive_data.items():
                for secret, description in items:
                    log_capture.records.clear()
                    log_capture.messages.clear()
                    
                    # Create error message containing the secret
                    error_msg = f"Authentication failed: Invalid {description} '{secret}' provided"
                    
                    with patch('subprocess.run') as mock_run:
                        mock_run.return_value = Mock(
                            returncode=1,
                            stdout='',
                            stderr=error_msg
                        )
                        
                        # Execute the function - should fail but sanitize logs
                        try:
                            result = process_file_documentation.call_local(
                                filepath='test_sensitive.py',
                                dataset_name='test_dataset',
                                commit_hash='abc123',
                                project_root=self.project_root
                            )
                        except Exception as e:
                            # Task will raise exception on error
                            pass
                    
                    # Verify secret is not in any log level
                    for record in log_capture.records:
                        self.assertNotIn(secret, record.getMessage(),
                            f"{description} '{secret}' found in {record.levelname} log: {record.getMessage()}")
                    
                    # Verify error was still logged (just sanitized)
                    error_logged = any('Failed to document' in msg or 'exit code 1' in msg 
                                     for msg in log_capture.messages)
                    self.assertTrue(error_logged, 
                        f"No error log found for {description} test")
            
            # Test 2: Database errors with credentials
            log_capture.records.clear()
            log_capture.messages.clear()
            
            db_error = "psycopg2.OperationalError: FATAL: password authentication failed for user 'admin' password='super_secret_123'"
            
            with patch('tasks.get_storage_server') as mock_storage:
                mock_storage.side_effect = Exception(db_error)
                
                try:
                    result = process_file_documentation.call_local(
                        filepath='test_sensitive.py',
                        dataset_name='test_dataset',
                        commit_hash='abc123',
                        project_root=self.project_root
                    )
                except Exception as e:
                    # Task will raise exception on error
                    pass
            
            # Check logs don't contain the password
            for record in log_capture.records:
                self.assertNotIn('super_secret_123', record.getMessage())
                self.assertNotIn("password='", record.getMessage())
            
            # Test 3: Mixed sensitive data in error messages
            log_capture.records.clear()
            log_capture.messages.clear()
            
            complex_error = """
            Failed to connect to API:
            - API Key: sk-1234567890abcdef
            - Token: ghp_abcdefghijklmnop
            - Database: postgres://admin:password123@localhost:5432/db
            - AWS: AKIA1234567890ABCDEF
            """
            
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=1,
                    stdout='',
                    stderr=complex_error
                )
                
                try:
                    result = process_file_documentation.call_local(
                        filepath='test_sensitive.py',
                        dataset_name='test_dataset',
                        commit_hash='abc123',
                        project_root=self.project_root
                    )
                except Exception as e:
                    # Task will raise exception on error
                    pass
            
            # Verify none of the secrets appear in logs
            secrets_in_error = [
                'sk-1234567890abcdef',
                'ghp_abcdefghijklmnop',
                'password123',
                'AKIA1234567890ABCDEF',
                'admin:password123'
            ]
            
            for record in log_capture.records:
                msg = record.getMessage()
                for secret in secrets_in_error:
                    self.assertNotIn(secret, msg,
                        f"Secret '{secret}' found in log: {msg}")
            
            # Test 4: Verify debug logs also sanitize
            debug_records = [r for r in log_capture.records if r.levelno == logging.DEBUG]
            self.assertGreater(len(debug_records), 0, "No debug logs captured")
            
            for record in debug_records:
                msg = record.getMessage()
                # Even debug logs should not contain secrets
                for category, items in sensitive_data.items():
                    for secret, _ in items:
                        self.assertNotIn(secret, msg,
                            f"Secret found in DEBUG log: {msg}")
            
            # Test 5: Check actual log file content
            # Force flush all handlers
            for handler in tasks_logger.handlers:
                if hasattr(handler, 'flush'):
                    handler.flush()
            
            with open(log_file_path, 'r') as f:
                file_contents = f.read()
                
                # Verify file doesn't contain any secrets
                all_secrets = []
                for category, items in sensitive_data.items():
                    all_secrets.extend([secret for secret, _ in items])
                
                for secret in all_secrets:
                    self.assertNotIn(secret, file_contents,
                        f"Secret '{secret}' found in log file")
                
                # Verify error messages are still logged (sanitized)
                self.assertTrue(
                    'Failed to document' in file_contents or 
                    'exit code 1' in file_contents or
                    'ERROR' in file_contents,
                    "No error indicators found in log file"
                )
            
            # Test 6: Verify sanitization doesn't break normal logging
            log_capture.records.clear()
            
            # Mock successful execution
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(
                    returncode=0,
                    stdout='{"overview": "Test file", "functions": {}}'
                )
                
                with patch('tasks.get_storage_server') as mock_storage:
                    mock_server = Mock()
                    mock_storage.return_value = mock_server
                    
                    result = process_file_documentation(
                        filepath='test_sensitive.py',
                        dataset_name='test_dataset',
                        commit_hash='abc123',
                        project_root=self.project_root
                    )
                    
                    self.assertTrue(result['success'])
            
            # Verify normal operation still logs appropriately
            info_logs = [r for r in log_capture.records if r.levelno == logging.INFO]
            self.assertGreater(len(info_logs), 0, "No info logs for successful operation")
            
            # Check for expected log messages
            log_messages = [r.getMessage() for r in log_capture.records]
            self.assertTrue(
                any('Processing documentation' in msg for msg in log_messages),
                "Missing processing start log"
            )
            self.assertTrue(
                any('Completed documentation' in msg for msg in log_messages),
                "Missing completion log"
            )
            
        finally:
            # Restore original logger state
            tasks_logger.removeHandler(log_capture)
            tasks_logger.setLevel(original_level)
            
            # Clean up log file
            if os.path.exists(log_file_path):
                os.unlink(log_file_path)
    
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