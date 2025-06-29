"""Lightweight worker detection for git hooks without external dependencies."""

import os
import json
import time
from typing import Optional, Tuple


def is_worker_running(project_root: str) -> bool:
    """
    Check if the background worker is running using lightweight methods.
    
    This function is designed for use in git hooks where we want minimal
    dependencies and fast execution.
    
    Args:
        project_root: Path to project root
        
    Returns:
        bool: True if worker appears to be running
    """
    pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
    if not os.path.exists(pid_file):
        return False
    
    try:
        # Read PID with validation
        with open(pid_file, 'r') as f:
            pid_str = f.read().strip()
        
        # Validate PID format
        if not pid_str or not pid_str.isdigit():
            return False
        
        pid = int(pid_str)
        if pid <= 0:
            return False
        
        # Check if process exists using os.kill with signal 0
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process doesn't exist
            return False
        except PermissionError:
            # We don't have permission to signal the process, but it exists.
            # This can be considered a success for a basic check.
            pass
        
        # Enhanced check: validate via /proc if available (Linux/Unix)
        if os.path.exists('/proc'):
            return _validate_via_proc(pid)
        
        # On systems without /proc, we can't validate further
        # but the process exists, so assume it's our worker
        return True
        
    except (ValueError, IOError):
        return False


def _validate_via_proc(pid: int) -> bool:
    """
    Validate that a process is our worker via /proc filesystem.
    
    Args:
        pid: Process ID to check
        
    Returns:
        bool: True if process appears to be our worker, False otherwise.
    """
    try:
        # Check cmdline to see if it's running huey
        cmdline_path = f'/proc/{pid}/cmdline'
        # Check existence first to handle race where process dies or permissions are denied
        if os.path.exists(cmdline_path):
            with open(cmdline_path, 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='replace')
                # Look for huey and tasks in the command line
                if 'huey' in cmdline and 'tasks' in cmdline:
                    return True
    except (IOError, OSError):  # Catch specific errors like FileNotFoundError, PermissionError
        # Could not read file or path error. Fall through to next check.
        pass
    
    # If cmdline check failed or didn't match, try checking the executable path.
    try:
        exe_path = f'/proc/{pid}/exe'
        if os.path.exists(exe_path):
            exe = os.readlink(exe_path)
            if 'python' in exe.lower():
                return True
    except (IOError, OSError):  # Catch specific errors like FileNotFoundError, PermissionError
        # Could not read link or path error. Fall through to fail.
        pass
    
    # If we could not positively identify the process through any of the checks,
    # we must assume it's NOT our worker (fail-closed principle).
    return False


def get_worker_info(project_root: str) -> Optional[dict]:
    """
    Get detailed worker information if available.
    
    Args:
        project_root: Path to project root
        
    Returns:
        dict: Worker info with keys 'pid', 'running', 'started_at' or None
    """
    pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
    if not os.path.exists(pid_file):
        return None
    
    try:
        # Get file modification time as proxy for start time
        started_at = os.path.getmtime(pid_file)
        
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        running = is_worker_running(project_root)
        
        return {
            'pid': pid,
            'running': running,
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started_at)),
            'uptime_seconds': int(time.time() - started_at) if running else 0
        }
        
    except (IOError, ValueError, FileNotFoundError):
        return None


def cleanup_stale_pid_file(project_root: str) -> bool:
    """
    Remove PID file if the worker is not actually running.
    
    Args:
        project_root: Path to project root
        
    Returns:
        bool: True if cleanup was performed
    """
    pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
    if not os.path.exists(pid_file):
        return False
    
    # Check if the worker is running. If it is, do nothing.
    # This check is still necessary to avoid trying to rename a file that's actively in use
    # by a *valid* process. The race condition is handled by the rename/unlink sequence below.
    if is_worker_running(project_root):
        return False

    # If worker is not running, atomically rename the pid file to a temporary name.
    # This prevents a race condition where a new worker starts and creates a new pid file
    # between our check and the deletion. If the rename succeeds, we know we have
    # exclusive control over the *stale* file that was present at the time of rename.
    stale_pid_file = pid_file + '.stale'
    try:
        # Attempt to rename the existing pid_file to stale_pid_file.
        # If pid_file doesn't exist (e.g., deleted by another process), FileNotFoundError is raised.
        os.rename(pid_file, stale_pid_file)
        # If rename succeeds, we now have the stale file under a new name.
        # We can safely remove it without affecting a potentially new worker.
        os.unlink(stale_pid_file)
        return True
    except FileNotFoundError:
        # The file was already removed by another process or didn't exist when rename was attempted.
        # This is fine, nothing to clean up by us.
        return False
    except OSError as e:
        # Other OS errors (e.g., permissions issues, disk full).
        # Log this if logging is available, but for a git hook, just return False.
        # print(f"Error cleaning up stale PID file: {e}") # For debugging
        return False