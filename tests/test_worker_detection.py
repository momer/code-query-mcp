import unittest
import tempfile
import os
import time
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.worker_manager import WorkerManager

class TestWorkerDetection(unittest.TestCase):
    """Test suite for worker detection functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
        os.makedirs(os.path.join(self.temp_dir, '.code-query'), exist_ok=True)
        self.worker_manager = WorkerManager(self.project_root)
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_no_pid_file(self):
        """Test detection when PID file doesn't exist."""
        is_running, pid = self.worker_manager._check_worker_status()
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
                is_running, pid = self.worker_manager._check_worker_status()
                
                self.assertTrue(is_running)
                self.assertEqual(pid, current_pid)
    
    def test_stale_pid_file(self):
        """Test cleanup of stale PID file."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        # Write non-existent PID
        with open(pid_file, 'w') as f:
            f.write('99999')
        
        with patch('psutil.pid_exists', return_value=False):
            is_running, pid = self.worker_manager._check_worker_status()
            
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
                is_running, pid = self.worker_manager._check_worker_status()
                
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
        
        is_running, pid = self.worker_manager._check_worker_status()
        
        self.assertFalse(is_running)
        self.assertIsNone(pid)
        # Corrupted file should be cleaned up
        self.assertFalse(os.path.exists(pid_file))
    
    def test_access_denied(self):
        """Test handling when process access is denied."""
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        
        with open(pid_file, 'w') as f:
            f.write('1234')
        
        import psutil
        with patch('psutil.pid_exists', return_value=True):
            with patch('psutil.Process') as mock_process_class:
                mock_process_class.side_effect = psutil.AccessDenied()
                
                is_running, pid = self.worker_manager._check_worker_status()
                
                self.assertFalse(is_running)
                self.assertIsNone(pid)
    
    @patch('subprocess.Popen')
    @patch('tasks.setup_logging')
    def test_start_worker(self, mock_setup_logging, mock_popen):
        """Test starting the worker process."""
        # Mock the subprocess
        mock_process = Mock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        # Mock psutil for verification
        with patch('psutil.pid_exists', return_value=True):
            with patch('psutil.Process') as mock_process_class:
                mock_proc = Mock()
                mock_proc.cmdline.return_value = ['huey_consumer', 'tasks.huey']
                mock_process_class.return_value = mock_proc
                
                success = self.worker_manager.start_worker()
                
                self.assertTrue(success)
                # Verify PID file was created
                pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
                self.assertTrue(os.path.exists(pid_file))
                with open(pid_file, 'r') as f:
                    self.assertEqual(f.read().strip(), '12345')