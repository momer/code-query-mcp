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
        """Test adding files to queue."""
        files = [
            ('test1.py', 'abc123'),
            ('test2.py', 'abc123')
        ]
        
        added_count = self.queue_manager.add_files(files)
        self.assertEqual(added_count, 2)
        
        # Verify files were added
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 2)
        self.assertEqual(queued_files[0]['filepath'], 'test1.py')
        self.assertTrue('queued_at' in queued_files[0])
    
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
        """Test that duplicates are handled correctly."""
        # Add same file multiple times
        self.queue_manager.add_files([('test.py', 'abc123')])
        time.sleep(0.1)  # Ensure different timestamp
        self.queue_manager.add_files([('test.py', 'def456')])
        
        # Should only have one entry (no duplicates by filepath)
        queued_files = self.queue_manager.list_queued_files()
        self.assertEqual(len(queued_files), 1)
    
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
    
    def test_atomic_operations(self):
        """Test that operations are atomic."""
        # This is a simplified test - real concurrency testing is complex
        files = [('test.py', 'abc123')]
        
        # Simulate concurrent add by making rename fail
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError("Simulated failure")
            
            # Should raise the exception
            with self.assertRaises(OSError):
                self.queue_manager.add_files(files)
            
            # Queue should remain unchanged
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
    
    def test_file_locking(self):
        """Test file locking mechanism."""
        import fcntl
        import threading
        import time
        
        # Test that operations are serialized by the lock
        results = []
        
        def add_files_with_delay():
            with self.queue_manager._acquire_lock():
                time.sleep(0.1)  # Hold lock briefly
                results.append('locked')
        
        # Start thread that will hold lock
        thread = threading.Thread(target=add_files_with_delay)
        thread.start()
        
        # Give thread time to acquire lock
        time.sleep(0.05)
        
        # This should block until thread releases lock
        start_time = time.time()
        with self.queue_manager._acquire_lock():
            results.append('acquired')
        elapsed = time.time() - start_time
        
        thread.join()
        
        # Should have waited for lock
        self.assertGreater(elapsed, 0.05)
        self.assertEqual(results, ['locked', 'acquired'])