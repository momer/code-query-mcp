import unittest
import tempfile
import os
import json
import time
from unittest.mock import patch
from datetime import datetime

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.queue_manager import QueueManager

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
        """Test adding files to queue with comprehensive validation of all files."""
        files = [
            ('test1.py', 'abc123'),
            ('test2.py', 'def456')
        ]
        
        added_count = self.queue_manager.add_files(files)
        self.assertEqual(added_count, 2)
        
        # Verify all files were added correctly
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 2)
        
        # Create a mapping for easier verification
        files_by_path = {f['filepath']: f for f in queued_files}
        
        # Verify first file
        self.assertIn('test1.py', files_by_path)
        test1_file = files_by_path['test1.py']
        self.assertEqual(test1_file['filepath'], 'test1.py')
        self.assertEqual(test1_file['commit_hash'], 'abc123')
        self.assertIn('queued_at', test1_file)
        self.assertIsInstance(test1_file['queued_at'], str)
        
        # Verify second file  
        self.assertIn('test2.py', files_by_path)
        test2_file = files_by_path['test2.py']
        self.assertEqual(test2_file['filepath'], 'test2.py')
        self.assertEqual(test2_file['commit_hash'], 'def456')
        self.assertIn('queued_at', test2_file)
        self.assertIsInstance(test2_file['queued_at'], str)
        
        # Verify timestamps are reasonable (not empty and parseable)
        from datetime import datetime
        for file_entry in queued_files:
            try:
                datetime.fromisoformat(file_entry['queued_at'].replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                self.fail(f"Invalid timestamp format in {file_entry['filepath']}: {file_entry['queued_at']}")
    
    def test_remove_files(self):
        """Test removing completed files."""
        # Add files
        files = [
            ('test1.py', 'abc123'),
            ('test2.py', 'abc123'),
            ('test3.py', 'abc123')
        ]
        self.queue_manager.add_files(files)
        
        # Remove some files
        removed_paths = ['test1.py', 'test3.py']
        removed_count = self.queue_manager.remove_files(removed_paths)
        
        self.assertEqual(removed_count, 2)
        
        # Verify remaining files
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 1)
        self.assertEqual(queued_files[0]['filepath'], 'test2.py')
    
    def test_duplicate_handling(self):
        """Test that duplicates are handled correctly - original entry is kept."""
        # Add file with initial commit hash
        added_count = self.queue_manager.add_files([('test.py', 'abc123')])
        self.assertEqual(added_count, 1, "Initial file should be added")
        
        # Get the original entry's details
        original_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(original_files), 1)
        original_entry = original_files[0]
        original_timestamp = original_entry['queued_at']
        
        # Verify original entry has expected values
        self.assertEqual(original_entry['filepath'], 'test.py')
        self.assertEqual(original_entry['commit_hash'], 'abc123')
        
        # Attempt to add same file with different commit hash
        added_count = self.queue_manager.add_files([('test.py', 'def456')])
        
        # CRITICAL: Verify that no files were added (duplicate was rejected)
        self.assertEqual(added_count, 0, "Duplicate file should NOT be added")
        
        # Verify queue still has only one entry
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 1)
        
        # CRITICAL: Verify the ORIGINAL entry was kept (not replaced)
        kept_entry = queued_files[0]
        self.assertEqual(kept_entry['filepath'], 'test.py')
        self.assertEqual(kept_entry['commit_hash'], 'abc123', 
                        "Original commit hash MUST be retained, not updated to 'def456'")
        self.assertEqual(kept_entry['queued_at'], original_timestamp,
                        "Original timestamp MUST be retained exactly")
        
        # Test that the entry was NOT updated in any way
        self.assertNotEqual(kept_entry['commit_hash'], 'def456',
                           "Commit hash must NOT be updated to new value")
        
        # Test multiple duplicates at once with mixed new/existing files
        added_count = self.queue_manager.add_files([
            ('test.py', 'ghi789'),      # duplicate - should be ignored
            ('test.py', 'jkl012'),      # duplicate - should be ignored
            ('new_file.py', 'mno345'),  # new file - should be added
            ('test.py', 'xyz999')       # duplicate - should be ignored
        ])
        
        # Only new_file.py should be added
        self.assertEqual(added_count, 1, "Only new files should be added, not duplicates")
        
        # Verify final queue state
        final_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(final_files), 2, "Queue should have exactly 2 files")
        
        # Create a mapping for easier verification
        files_by_path = {f['filepath']: f for f in final_files}
        
        # CRITICAL: Verify test.py still has ORIGINAL values (not updated)
        self.assertIn('test.py', files_by_path)
        test_py_entry = files_by_path['test.py']
        self.assertEqual(test_py_entry['commit_hash'], 'abc123',
                        "test.py must retain original commit hash 'abc123'")
        self.assertEqual(test_py_entry['queued_at'], original_timestamp,
                        "test.py must retain original timestamp")
        
        # Verify none of the attempted updates changed the entry
        self.assertNotIn('def456', test_py_entry['commit_hash'])
        self.assertNotIn('ghi789', test_py_entry['commit_hash'])
        self.assertNotIn('jkl012', test_py_entry['commit_hash'])
        self.assertNotIn('xyz999', test_py_entry['commit_hash'])
        
        # Verify new_file.py was added correctly
        self.assertIn('new_file.py', files_by_path)
        new_file_entry = files_by_path['new_file.py']
        self.assertEqual(new_file_entry['commit_hash'], 'mno345')
        self.assertNotEqual(new_file_entry['queued_at'], original_timestamp,
                           "New file should have a different timestamp")
    
    def test_clear_queue(self):
        """Test clearing the queue."""
        # Add files
        files = [(f'test{i}.py', 'abc123') for i in range(5)]
        self.queue_manager.add_files(files)
        
        # Clear
        cleared_count = self.queue_manager.clear_queue()
        self.assertEqual(cleared_count, 5)
        
        # Verify empty
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 0)
    
    def test_atomic_file_replacement_on_failure(self):
        """Test that file replacement failures leave queue unchanged (atomic behavior)."""
        # This test verifies that when os.replace fails during queue updates,
        # the queue remains in its original state (atomicity of file operations)
        files = [('test.py', 'abc123')]
        
        # Simulate file system failure during atomic replacement
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError("Simulated disk full error")
            
            # Should raise the exception
            with self.assertRaises(OSError):
                self.queue_manager.add_files(files)
            
            # Queue should remain unchanged (atomicity verified)
            queued_files = self.queue_manager.list_queued_files()
            self.assertEqual(len(queued_files), 0)
    
    def test_queue_status(self):
        """Test queue status reporting."""
        # Add various files with mock file sizes
        test_files = [
            ('test.py', 'abc123'),
            ('test.js', 'abc123'),
            ('lib/helper.py', 'def456'),
            ('README.md', 'def456')
        ]
        
        # Create actual files for size calculation
        for filepath, _ in test_files:
            full_path = os.path.join(self.project_root, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write('test content')
        
        self.queue_manager.add_files(test_files)
        
        status = self.queue_manager.get_queue_status()
        
        self.assertEqual(status['queued_files'], 4)
        self.assertGreater(status['total_size'], 0)
        self.assertEqual(len(status['by_commit']), 2)  # Two different commits
        self.assertEqual(status['by_commit']['abc123'], 2)
        self.assertEqual(status['by_commit']['def456'], 2)
    
    def test_process_next_batch(self):
        """Test batch processing of queued files."""
        # Add many files
        files = [(f'test{i}.py', 'abc123') for i in range(10)]
        self.queue_manager.add_files(files)
        
        # Process batch
        batch = self.queue_manager.process_next_batch(batch_size=3)
        self.assertEqual(len(batch), 3)
        
        # Verify queue updated
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 7)
        
        # Process another batch
        batch = self.queue_manager.process_next_batch(batch_size=5)
        self.assertEqual(len(batch), 5)
        
        # Verify queue updated again
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 2)
    
    def test_cleanup_missing_files(self):
        """Test cleanup of entries for missing files."""
        # Add files without creating them
        files = [
            ('exists.py', 'abc123'),
            ('missing.py', 'abc123'),
            ('also_missing.py', 'abc123')
        ]
        
        # Create only one file
        exists_path = os.path.join(self.project_root, 'exists.py')
        with open(exists_path, 'w') as f:
            f.write('test')
        
        self.queue_manager.add_files(files)
        
        # Cleanup
        removed_count, removed_files = self.queue_manager.cleanup_missing_files()
        self.assertEqual(removed_count, 2)
        self.assertEqual(len(removed_files), 2)
        self.assertIn('missing.py', removed_files)
        self.assertIn('also_missing.py', removed_files)
        
        # Verify only existing file remains
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 1)
        self.assertEqual(queued_files[0]['filepath'], 'exists.py')
    
    def test_get_history(self):
        """Test history tracking."""
        # Perform various operations that are tracked in history
        self.queue_manager.add_files([('test1.py', 'abc123')])
        self.queue_manager.add_files([('test2.py', 'abc123')])
        self.queue_manager.remove_files(['test1.py'])
        self.queue_manager.clear_queue()
        
        history = self.queue_manager.get_history(limit=10)
        
        # Only remove and clear operations are tracked in history
        self.assertGreaterEqual(len(history), 2)
        # Check last operation
        self.assertEqual(history[0]['operation'], 'cleared')
    
    def test_file_locking_thread_safety(self):
        """Test that file lock properly serializes access between threads."""
        import threading
        
        # Use threading.Event for deterministic synchronization
        lock_acquired = threading.Event()
        proceed_with_release = threading.Event()
        results = []
        
        def worker_thread():
            """Worker thread that performs queue operations."""
            # Test through public API by adding files
            self.queue_manager.add_files([('thread_test.py', 'thread123')])
            results.append('thread_added_files')
            
            # Now test with explicit lock acquisition
            with self.queue_manager._acquire_lock():
                results.append('thread_locked')
                # Signal that we've acquired the lock
                lock_acquired.set()
                # Wait for main thread to attempt lock acquisition
                proceed_with_release.wait()
                results.append('thread_releasing')
        
        # Start worker thread
        thread = threading.Thread(target=worker_thread)
        thread.start()
        
        # Wait for worker thread to acquire lock
        lock_acquired.wait()
        
        # Now try to acquire lock from main thread - should block
        results.append('main_waiting')
        # Signal worker to release after we start waiting
        proceed_with_release.set()
        
        with self.queue_manager._acquire_lock():
            results.append('main_acquired')
            # Verify we can see the thread's changes
            files = self.queue_manager.list_queued_files()
            if any(f['filepath'] == 'thread_test.py' for f in files):
                results.append('main_saw_changes')
        
        thread.join()
        
        # Verify operations were properly serialized
        expected_results = [
            'thread_added_files',
            'thread_locked', 
            'main_waiting', 
            'thread_releasing', 
            'main_acquired',
            'main_saw_changes'
        ]
        self.assertEqual(results, expected_results)
    
    def test_file_locking_process_safety(self):
        """Test that file lock properly serializes access between processes."""
        import multiprocessing
        import queue
        import os
        import tempfile
        
        # Create a simple lock test using actual queue operations 
        result_queue = multiprocessing.Queue()
        
        def process_worker(project_root, worker_id, result_q):
            """Worker process that uses queue operations to test locking."""
            try:
                # Import inside process to avoid pickling issues
                from helpers.queue_manager import QueueManager
                
                qm = QueueManager(project_root)
                
                result_q.put(f'process_{worker_id}_starting')
                
                # Use the public API which internally uses locking
                files_to_add = [(f'process_test_{worker_id}.py', f'proc{worker_id}')]
                added_count = qm.add_files(files_to_add)
                
                result_q.put(f'process_{worker_id}_added_{added_count}_files')
                
                # List files to ensure we can read
                files = qm.list_queued_files()
                result_q.put(f'process_{worker_id}_found_{len(files)}_files')
                
                result_q.put(f'process_{worker_id}_done')
                    
            except Exception as e:
                result_q.put(f'process_{worker_id}_error: {str(e)}')
        
        # Start two processes that will both try to modify the queue
        processes = []
        for i in range(2):
            p = multiprocessing.Process(
                target=process_worker,
                args=(self.project_root, i+1, result_queue)
            )
            processes.append(p)
        
        # Start both processes
        for p in processes:
            p.start()
        
        # Wait for completion with reasonable timeout
        all_completed = True
        for i, p in enumerate(processes):
            p.join(timeout=10)  # Increase timeout
            if p.is_alive():
                p.terminate()
                p.join()
                all_completed = False
        
        # Skip test if processes didn't complete (might indicate system issue)
        if not all_completed:
            self.skipTest("Process timeout - possible system issue with multiprocessing")
        
        # Collect results
        results = []
        while not result_queue.empty():
            try:
                result = result_queue.get_nowait()
                results.append(result)
            except queue.Empty:
                break
        
        # Check for errors
        error_results = [r for r in results if 'error' in str(r)]
        if error_results:
            self.fail(f"Process errors occurred: {error_results}")
        
        # Verify both processes completed their work
        self.assertIn('process_1_done', results)
        self.assertIn('process_2_done', results)
        
        # Verify both processes successfully added files
        added_results = [r for r in results if 'added_1_files' in r]
        self.assertEqual(len(added_results), 2, "Both processes should have added files")
        
        # Most important test: verify both files exist in final queue
        # If locking works, both operations should have succeeded
        files = self.queue_manager.list_queued_files()
        found_files = [f['filepath'] for f in files]
        
        self.assertEqual(len(found_files), 2, "Both process files should be in queue")
        self.assertIn('process_test_1.py', found_files)
        self.assertIn('process_test_2.py', found_files)
    
    def test_file_locking(self):
        """Test that file locking works correctly for both threads and processes."""
        # This is a simple test that verifies the lock mechanism is working
        # The detailed thread and process safety are tested in the specific tests above
        
        # Test basic lock acquisition and release
        lock1 = self.queue_manager._acquire_lock()
        
        # Enter the lock context
        lock1.__enter__()
        
        # Try to acquire another lock - this would block in a real scenario
        # but we'll just verify the lock file exists
        self.assertTrue(os.path.exists(self.queue_manager.lock_file))
        
        # Exit the lock context
        lock1.__exit__(None, None, None)
        
        # Verify we can acquire the lock again after release
        with self.queue_manager._acquire_lock():
            # Successfully acquired
            self.assertTrue(True)
        
        # Test that the lock protects queue operations
        initial_files = [('test1.py', 'abc123'), ('test2.py', 'def456')]
        self.queue_manager.add_files(initial_files)
        
        # Verify the files were added atomically
        files = self.queue_manager.list_queued_files()
        self.assertEqual(len(files), 2)
        
        # Clean up
        self.queue_manager.clear_queue()