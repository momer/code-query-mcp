# Step 4: Worker Detection Implementation

## Overview
Implement reliable worker detection using PID files with automatic cleanup of stale entries.

## References
- phase1_pr_plan.md:115-135
- Zen's feedback on PID-based detection

## Implementation Tasks

### 4.1 Create helpers/worker_detector.py

```python
import os
import psutil
from typing import Tuple, Optional

class WorkerDetector:
    """Detect and verify worker process status."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
    def is_worker_running(self) -> Tuple[bool, Optional[int]]:
        """
        Check if the worker process is running.
        
        Returns:
            Tuple[bool, Optional[int]]: (is_running, pid)
            - is_running: True if worker is running
            - pid: Process ID if running, None otherwise
        """
        # Check if PID file exists
        if not os.path.exists(self.pid_file):
            return False, None
        
        try:
            # Read PID from file
            with open(self.pid_file, 'r') as f:
                pid_str = f.read().strip()
                
            # Validate PID format
            if not pid_str.isdigit():
                self._cleanup_invalid_pid_file("Invalid PID format")
                return False, None
                
            pid = int(pid_str)
            
            # Check if process exists
            if not psutil.pid_exists(pid):
                self._cleanup_stale_pid_file(pid)
                return False, None
            
            # Verify it's actually our worker process
            try:
                process = psutil.Process(pid)
                cmdline = ' '.join(process.cmdline())
                
                # Check for Huey worker indicators
                if 'huey' in cmdline and 'tasks.huey' in cmdline:
                    return True, pid
                else:
                    # PID exists but it's not our worker (PID reuse)
                    self._cleanup_stale_pid_file(pid, reason="PID reused by different process")
                    return False, None
                    
            except psutil.NoSuchProcess:
                # Process disappeared between checks
                self._cleanup_stale_pid_file(pid)
                return False, None
            except psutil.AccessDenied:
                # Can't access process info - assume it's not ours
                self._cleanup_stale_pid_file(pid, reason="Access denied to process")
                return False, None
                
        except (IOError, ValueError) as e:
            # Error reading or parsing PID file
            self._cleanup_invalid_pid_file(f"Error reading PID file: {e}")
            return False, None
    
    def _cleanup_stale_pid_file(self, pid: int, reason: str = "Process not found"):
        """
        Remove stale PID file and log the reason.
        
        Args:
            pid: The stale PID
            reason: Why the PID is considered stale
        """
        try:
            os.unlink(self.pid_file)
            # Log to worker log if it exists
            log_file = os.path.join(self.project_root, '.code-query', 'worker.log')
            if os.path.exists(log_file):
                with open(log_file, 'a') as f:
                    import datetime
                    timestamp = datetime.datetime.now().isoformat()
                    f.write(f"\n[{timestamp}] Cleaned up stale PID file (PID: {pid}, Reason: {reason})\n")
        except OSError:
            pass  # Best effort cleanup
    
    def _cleanup_invalid_pid_file(self, reason: str):
        """
        Remove invalid PID file.
        
        Args:
            reason: Why the PID file is invalid
        """
        try:
            os.unlink(self.pid_file)
            # Log the cleanup
            log_file = os.path.join(self.project_root, '.code-query', 'worker.log')
            if os.path.exists(log_file):
                with open(log_file, 'a') as f:
                    import datetime
                    timestamp = datetime.datetime.now().isoformat()
                    f.write(f"\n[{timestamp}] Cleaned up invalid PID file (Reason: {reason})\n")
        except OSError:
            pass

    def get_worker_info(self) -> Optional[dict]:
        """
        Get detailed information about the running worker.
        
        Returns:
            Optional[dict]: Worker info if running, None otherwise
        """
        is_running, pid = self.is_worker_running()
        
        if not is_running:
            return None
        
        try:
            process = psutil.Process(pid)
            
            return {
                'pid': pid,
                'status': process.status(),
                'create_time': process.create_time(),
                'cpu_percent': process.cpu_percent(interval=0.1),
                'memory_info': {
                    'rss': process.memory_info().rss,
                    'vms': process.memory_info().vms,
                    'percent': process.memory_percent()
                },
                'num_threads': process.num_threads(),
                'cmdline': process.cmdline()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None


# Standalone function for backward compatibility
def is_worker_running(project_root: Optional[str] = None) -> Tuple[bool, Optional[int]]:
    """
    Check if worker is running (standalone function).
    
    Args:
        project_root: Project root directory (defaults to current directory)
        
    Returns:
        Tuple[bool, Optional[int]]: (is_running, pid)
    """
    if project_root is None:
        project_root = os.getcwd()
    
    detector = WorkerDetector(project_root)
    return detector.is_worker_running()
```

### 4.2 Create lightweight detection for git hooks

Since git hooks shouldn't depend on psutil, create a minimal detector:

```python
def is_worker_running_minimal(project_root: str) -> bool:
    """
    Minimal worker detection without psutil dependency.
    Used by git hooks to avoid heavy dependencies.
    
    Args:
        project_root: Project root directory
        
    Returns:
        bool: True if worker appears to be running
    """
    pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
    if not os.path.exists(pid_file):
        return False
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        # Use os.kill with signal 0 to check if process exists
        # This works on Unix and Windows without additional dependencies
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            # Process doesn't exist
            # Note: We can't clean up the PID file here without psutil
            # to verify it's actually our process
            return False
            
    except (ValueError, IOError, OSError):
        return False
```

### 4.3 Add worker health check

```python
def check_worker_health(project_root: str) -> dict:
    """
    Perform comprehensive health check on the worker.
    
    Args:
        project_root: Project root directory
        
    Returns:
        dict: Health check results
    """
    detector = WorkerDetector(project_root)
    is_running, pid = detector.is_worker_running()
    
    health = {
        'is_running': is_running,
        'pid': pid,
        'checks': {
            'pid_file_exists': os.path.exists(detector.pid_file),
            'pid_file_readable': False,
            'process_exists': False,
            'process_is_huey': False,
            'process_responsive': False
        }
    }
    
    if os.path.exists(detector.pid_file):
        try:
            with open(detector.pid_file, 'r') as f:
                f.read()
            health['checks']['pid_file_readable'] = True
        except IOError:
            pass
    
    if pid and is_running:
        health['checks']['process_exists'] = True
        
        # Check if it's Huey
        info = detector.get_worker_info()
        if info:
            cmdline = ' '.join(info.get('cmdline', []))
            if 'huey' in cmdline:
                health['checks']['process_is_huey'] = True
            
            # Check if process is responsive (not hung)
            if info.get('status') != 'zombie':
                health['checks']['process_responsive'] = True
    
    # Overall health status
    health['status'] = 'healthy' if all(health['checks'].values()) else 'unhealthy'
    
    return health
```

## Testing Checklist
- [ ] Detects running worker correctly
- [ ] Returns correct PID
- [ ] Cleans up stale PID files automatically
- [ ] Handles PID reuse correctly
- [ ] Works without psutil (minimal version)
- [ ] Logs cleanup actions
- [ ] Health check provides accurate diagnostics
- [ ] Thread-safe file operations

## Edge Cases
- PID file exists but process doesn't
- PID file exists but different process using that PID
- Corrupted PID file (non-numeric content)
- PID file not readable (permissions)
- Process exists but not accessible (permissions)
- Process disappears during check