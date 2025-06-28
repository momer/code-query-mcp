# Step 5: Queue Management

## Overview
Implement atomic queue operations with proper handling of concurrent access and partial processing.

## References
- automated_queue_processing_plan.md:67-74
- Zen's feedback on atomic operations and race conditions

## Implementation Tasks

### 5.1 Extend queue handling in storage layer

Create or extend `storage/queue_manager.py`:

```python
import os
import json
import time
import fcntl  # Unix file locking
from typing import List, Dict, Optional, Any
from datetime import datetime
from contextlib import contextmanager

class QueueManager:
    """
    Manages the file processing queue with atomic operations.
    Handles concurrent access from multiple processes.
    """
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
        self.lock_file = self.queue_file + '.lock'
        os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
    
    @contextmanager
    def _file_lock(self, timeout: float = 5.0):
        """
        Acquire exclusive lock on the queue file.
        
        Args:
            timeout: Maximum time to wait for lock
            
        Yields:
            None
            
        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        lock_fd = None
        start_time = time.time()
        
        try:
            # Open or create lock file
            lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR)
            
            # Try to acquire exclusive lock
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except IOError:
                    # Lock is held by another process
                    if time.time() - start_time > timeout:
                        raise TimeoutError(f"Could not acquire lock on {self.lock_file} within {timeout}s")
                    time.sleep(0.1)
            
            yield
            
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except:
                    pass
    
    def add_files(self, files: List[Dict[str, Any]]) -> bool:
        """
        Add files to the queue atomically.
        
        Args:
            files: List of file info dicts with at least 'filepath' key
            
        Returns:
            bool: True if files were added successfully
        """
        try:
            with self._file_lock():
                # Read current queue
                current_queue = self._read_queue_unsafe()
                
                # Add timestamp and default commit hash if not present
                for file_info in files:
                    if 'timestamp' not in file_info:
                        file_info['timestamp'] = datetime.now().isoformat()
                    if 'commit_hash' not in file_info:
                        file_info['commit_hash'] = self._get_current_commit_hash()
                
                # Append new files
                current_queue['files'].extend(files)
                
                # Remove duplicates (keep newest)
                seen = {}
                unique_files = []
                for file_info in reversed(current_queue['files']):
                    filepath = file_info['filepath']
                    if filepath not in seen:
                        seen[filepath] = True
                        unique_files.append(file_info)
                
                current_queue['files'] = list(reversed(unique_files))
                
                # Write back atomically
                self._write_queue_unsafe(current_queue)
                return True
                
        except Exception as e:
            print(f"Error adding files to queue: {e}")
            return False
    
    def get_snapshot(self, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get a snapshot of files from the queue.
        Does not modify the queue.
        
        Args:
            max_items: Maximum number of items to return
            
        Returns:
            List[Dict]: List of file info dicts
        """
        try:
            with self._file_lock():
                queue_data = self._read_queue_unsafe()
                files = queue_data.get('files', [])
                
                if max_items:
                    return files[:max_items]
                return files.copy()
                
        except Exception:
            return []
    
    def remove_files(self, completed_files: List[Dict[str, Any]]) -> int:
        """
        Remove completed files from the queue atomically.
        
        Args:
            completed_files: List of file info dicts that were processed
            
        Returns:
            int: Number of files removed
        """
        if not completed_files:
            return 0
        
        try:
            with self._file_lock():
                # Read current queue
                queue_data = self._read_queue_unsafe()
                original_count = len(queue_data.get('files', []))
                
                # Create set of completed file paths for efficient lookup
                completed_paths = {f['filepath'] for f in completed_files}
                
                # Filter out completed files
                remaining_files = [
                    f for f in queue_data.get('files', [])
                    if f['filepath'] not in completed_paths
                ]
                
                queue_data['files'] = remaining_files
                
                # Write back atomically
                self._write_queue_unsafe(queue_data)
                
                removed_count = original_count - len(remaining_files)
                return removed_count
                
        except Exception as e:
            print(f"Error removing files from queue: {e}")
            return 0
    
    def clear_queue(self) -> bool:
        """
        Clear all files from the queue.
        
        Returns:
            bool: True if queue was cleared successfully
        """
        try:
            with self._file_lock():
                empty_queue = {
                    'files': [],
                    'last_cleared': datetime.now().isoformat()
                }
                self._write_queue_unsafe(empty_queue)
                return True
                
        except Exception as e:
            print(f"Error clearing queue: {e}")
            return False
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current queue.
        
        Returns:
            Dict: Queue statistics
        """
        try:
            with self._file_lock():
                queue_data = self._read_queue_unsafe()
                files = queue_data.get('files', [])
                
                stats = {
                    'total_files': len(files),
                    'oldest_timestamp': None,
                    'newest_timestamp': None,
                    'file_types': {},
                    'queue_size_bytes': 0
                }
                
                if files:
                    # Get timestamp range
                    timestamps = [f.get('timestamp') for f in files if f.get('timestamp')]
                    if timestamps:
                        stats['oldest_timestamp'] = min(timestamps)
                        stats['newest_timestamp'] = max(timestamps)
                    
                    # Count file types
                    for f in files:
                        ext = os.path.splitext(f['filepath'])[1].lower()
                        stats['file_types'][ext] = stats['file_types'].get(ext, 0) + 1
                
                # Get queue file size
                if os.path.exists(self.queue_file):
                    stats['queue_size_bytes'] = os.path.getsize(self.queue_file)
                
                return stats
                
        except Exception:
            return {'error': 'Could not read queue stats'}
    
    def _read_queue_unsafe(self) -> Dict[str, Any]:
        """
        Read queue file without locking.
        Should only be called within a lock context.
        """
        if not os.path.exists(self.queue_file):
            return {'files': []}
        
        try:
            with open(self.queue_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Corrupted or empty file
            return {'files': []}
    
    def _write_queue_unsafe(self, queue_data: Dict[str, Any]):
        """
        Write queue file atomically without locking.
        Should only be called within a lock context.
        """
        # Write to temporary file
        temp_file = self.queue_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(queue_data, f, indent=2)
        
        # Atomic rename
        os.replace(temp_file, self.queue_file)
    
    def _get_current_commit_hash(self) -> str:
        """Get current git commit hash."""
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=self.project_root
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]  # Short hash
        except:
            pass
        return 'unknown'


# Cross-platform file locking fallback
if os.name == 'nt':  # Windows
    import msvcrt
    
    # Override the _file_lock method for Windows
    def _file_lock_windows(self, timeout: float = 5.0):
        """Windows implementation of file locking."""
        lock_fd = None
        start_time = time.time()
        
        try:
            while True:
                try:
                    # Try to open lock file exclusively
                    lock_fd = os.open(
                        self.lock_file, 
                        os.O_CREAT | os.O_EXCL | os.O_RDWR
                    )
                    break
                except OSError:
                    # File exists, someone has the lock
                    if time.time() - start_time > timeout:
                        raise TimeoutError(f"Could not acquire lock within {timeout}s")
                    time.sleep(0.1)
            
            yield
            
        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                    os.unlink(self.lock_file)
                except:
                    pass
    
    # Monkey-patch for Windows
    QueueManager._file_lock = _file_lock_windows
```

### 5.2 Create queue monitoring utilities

```python
class QueueMonitor:
    """Monitor and report on queue health."""
    
    def __init__(self, queue_manager: QueueManager):
        self.queue_manager = queue_manager
    
    def check_queue_health(self) -> Dict[str, Any]:
        """
        Check queue health and report issues.
        
        Returns:
            Dict: Health check results
        """
        health = {
            'status': 'healthy',
            'issues': [],
            'stats': {}
        }
        
        try:
            # Get queue stats
            stats = self.queue_manager.get_queue_stats()
            health['stats'] = stats
            
            # Check for issues
            if stats.get('total_files', 0) > 100:
                health['issues'].append({
                    'severity': 'warning',
                    'message': f"Large queue size: {stats['total_files']} files pending"
                })
            
            if stats.get('queue_size_bytes', 0) > 10 * 1024 * 1024:  # 10MB
                health['issues'].append({
                    'severity': 'warning',
                    'message': f"Large queue file: {stats['queue_size_bytes'] / 1024 / 1024:.1f} MB"
                })
            
            # Check age of oldest item
            if stats.get('oldest_timestamp'):
                try:
                    oldest = datetime.fromisoformat(stats['oldest_timestamp'])
                    age_hours = (datetime.now() - oldest).total_seconds() / 3600
                    if age_hours > 24:
                        health['issues'].append({
                            'severity': 'warning',
                            'message': f"Stale items in queue: oldest is {age_hours:.1f} hours old"
                        })
                except:
                    pass
            
            # Set overall status
            if any(i['severity'] == 'error' for i in health['issues']):
                health['status'] = 'error'
            elif any(i['severity'] == 'warning' for i in health['issues']):
                health['status'] = 'warning'
            
        except Exception as e:
            health['status'] = 'error'
            health['issues'].append({
                'severity': 'error',
                'message': f"Could not check queue health: {e}"
            })
        
        return health
```

## Testing Checklist
- [ ] Concurrent access is handled properly
- [ ] File locking works on Unix and Windows
- [ ] Atomic writes prevent corruption
- [ ] Duplicate files are handled correctly
- [ ] Partial processing updates queue correctly
- [ ] Queue stats are accurate
- [ ] Large queues are handled efficiently
- [ ] Lock timeouts work as expected

## Performance Considerations
- Use file locking sparingly (batch operations)
- Consider queue size limits
- Implement queue archiving for old items
- Monitor lock contention in high-concurrency scenarios