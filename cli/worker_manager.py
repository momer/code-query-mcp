import os
import sys
import subprocess
import signal
import time
import json
from typing import Optional, Tuple
import psutil

class WorkerManager:
    """Manages the Huey worker process lifecycle."""
    
    def __init__(self, project_root: str):
        # Validate and normalize project root
        self.project_root = os.path.realpath(project_root)
        if not os.path.isdir(self.project_root):
            raise ValueError(f"Project root does not exist: {project_root}")
        
        # Define paths with security in mind
        self.code_query_dir = os.path.join(self.project_root, '.code-query')
        self.pid_file = os.path.join(self.code_query_dir, 'worker.pid')
        self.log_file = os.path.join(self.code_query_dir, 'logs', 'worker.log')
        self.config_file = os.path.join(self.code_query_dir, 'config.json')
    
    def start_worker(self) -> bool:
        """
        Start the Huey worker process with proper daemonization.
        
        Returns:
            bool: True if worker started successfully
        """
        # Check if worker is already running
        is_running, existing_pid = self._check_worker_status()
        if is_running:
            print(f"✓ Worker already running (PID: {existing_pid})")
            return True
        
        # Ensure directories exist with proper permissions
        os.makedirs(os.path.dirname(self.pid_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        # Set up logging for the worker
        from tasks import setup_logging
        setup_logging(self.log_file)
        
        # Build the huey_consumer command
        # Important: We need to ensure tasks.py is importable
        env = os.environ.copy()
        env['PYTHONPATH'] = self.project_root + ':' + env.get('PYTHONPATH', '')
        env['HUEY_WORKER_START_TIME'] = str(time.time())  # For health checks
        
        cmd = [
            'huey_consumer',  # Huey's consumer command
            'tasks.huey',  # Import path to our huey instance
            '--workers', '1',  # Single worker for simplicity
            '--logfile', self.log_file,
            '--verbose'
        ]
        
        try:
            # Open log file for output redirection
            with open(self.log_file, 'a') as log_file_handle:
                # Launch huey_consumer as subprocess
                # preexec_fn=os.setsid for Unix daemonization
                p = subprocess.Popen(
                    cmd,
                    stdout=log_file_handle,
                    stderr=subprocess.STDOUT,  # Merge stderr into stdout
                    preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
                    cwd=self.project_root,
                    env=env
                )
                
                # Capture the actual worker PID
                worker_pid = p.pid
                
                # Write PID atomically to prevent race conditions
                temp_pid_file = self.pid_file + '.tmp'
                with open(temp_pid_file, 'w') as f:
                    f.write(str(worker_pid))
                os.replace(temp_pid_file, self.pid_file)
                
                # Give the worker a moment to start
                time.sleep(2)
                
                # Verify it's still running
                if psutil.pid_exists(worker_pid):
                    # Double-check it's our process
                    try:
                        proc = psutil.Process(worker_pid)
                        cmdline = ' '.join(proc.cmdline())
                        if 'huey' in cmdline:
                            print(f"✓ Worker started successfully (PID: {worker_pid})")
                            print(f"  Log file: {self.log_file}")
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                print("✗ Worker process died immediately after starting")
                print(f"  Check log file: {self.log_file}")
                self._cleanup_pid_file()
                return False
                
        except Exception as e:
            print(f"✗ Failed to start worker: {e}")
            return False
    
    def stop_worker(self) -> bool:
        """
        Stop the worker process gracefully.
        
        Returns:
            bool: True if worker stopped successfully
        """
        is_running, pid = self._check_worker_status()
        
        if not is_running:
            print("✓ Worker is not running")
            return True
        
        try:
            # Send SIGTERM for graceful shutdown
            os.kill(pid, signal.SIGTERM)
            print(f"  Sent SIGTERM to worker (PID: {pid})")
            
            # Wait up to 10 seconds for graceful shutdown
            for i in range(10):
                time.sleep(1)
                if not psutil.pid_exists(pid):
                    print(f"✓ Worker stopped gracefully (PID: {pid})")
                    self._cleanup_pid_file()
                    return True
            
            # If still running, force kill
            print("  Worker didn't stop gracefully, forcing...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
            
            if not psutil.pid_exists(pid):
                print(f"✓ Worker force stopped (PID: {pid})")
                self._cleanup_pid_file()
                return True
            else:
                print(f"✗ Failed to stop worker (PID: {pid})")
                return False
                
        except ProcessLookupError:
            # Process already dead
            print(f"✓ Worker process already terminated")
            self._cleanup_pid_file()
            return True
        except Exception as e:
            print(f"✗ Error stopping worker: {e}")
            return False
    
    def restart_worker(self) -> bool:
        """
        Restart the worker process.
        
        Returns:
            bool: True if worker restarted successfully
        """
        print("Restarting worker...")
        
        # Stop if running
        if self._check_worker_status()[0]:
            if not self.stop_worker():
                return False
            time.sleep(2)  # Brief pause between stop and start
        
        # Start worker
        return self.start_worker()
    
    def get_worker_status(self) -> Tuple[bool, Optional[int]]:
        """
        Get the current worker status.
        
        Returns:
            Tuple[bool, Optional[int]]: (is_running, pid)
        """
        return self._check_worker_status()
    
    def display_worker_status(self):
        """Display detailed worker status information."""
        is_running, pid = self._check_worker_status()
        
        print("Worker Status")
        print("=" * 40)
        
        if is_running:
            print(f"Status: ✓ Running")
            print(f"PID: {pid}")
            
            # Get process info
            try:
                proc = psutil.Process(pid)
                print(f"CPU: {proc.cpu_percent(interval=0.1):.1f}%")
                print(f"Memory: {proc.memory_info().rss / 1024 / 1024:.1f} MB")
                print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(proc.create_time()))}")
            except psutil.NoSuchProcess:
                pass
        else:
            print("Status: ✗ Not running")
        
        # Check configuration
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    mode = config.get('processing', {}).get('mode', 'manual')
                    print(f"Mode: {mode}")
            except (json.JSONDecodeError, IOError):
                print("Mode: <error reading config>")
        
        # Check log file
        if os.path.exists(self.log_file):
            try:
                size = os.path.getsize(self.log_file) / 1024  # KB
                print(f"Log file: {self.log_file} ({size:.1f} KB)")
                
                # Show last few lines of log
                print("\nRecent log entries:")
                print("-" * 40)
                with open(self.log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-5:]:  # Last 5 lines
                        print(f"  {line.rstrip()}")
            except IOError:
                print(f"Log file: <error reading {self.log_file}>")
    
    def _check_worker_status(self) -> Tuple[bool, Optional[int]]:
        """
        Check if worker is running by examining PID file.
        
        Returns:
            Tuple[bool, Optional[int]]: (is_running, pid)
        """
        if not os.path.exists(self.pid_file):
            return False, None
        
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process with this PID exists
            if psutil.pid_exists(pid):
                # Verify it's actually our worker (not PID reuse)
                try:
                    proc = psutil.Process(pid)
                    cmdline = ' '.join(proc.cmdline())
                    if 'huey' in cmdline and 'tasks.huey' in cmdline:
                        return True, pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # PID doesn't exist or isn't our worker - clean up stale file
            self._cleanup_pid_file()
            return False, None
            
        except (ValueError, IOError):
            # Corrupted or inaccessible PID file
            self._cleanup_pid_file()
            return False, None
    
    def _cleanup_pid_file(self):
        """Remove PID file if it exists."""
        try:
            if os.path.exists(self.pid_file):
                os.unlink(self.pid_file)
        except OSError:
            pass