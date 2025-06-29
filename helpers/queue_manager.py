"""Queue management for file documentation processing."""

import os
import json
import fcntl  # Unix-specific, not available on Windows
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class QueueManager:
    """Manages the file documentation queue with atomic operations."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
        self.lock_file = os.path.join(project_root, '.code-query', 'queue.lock')
        self.history_file = os.path.join(project_root, '.code-query', 'queue_history.json')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
    
    def get_queue_status(self) -> Dict:
        """Get current queue status and statistics."""
        queue_data = self._load_queue()
        
        if not queue_data:
            return {
                'status': 'empty',
                'queued_files': 0,
                'total_size': 0,
                'oldest_entry': None,
                'newest_entry': None,
                'by_commit': {}
            }
        
        files = queue_data.get('files', [])
        
        # Calculate statistics
        total_size = 0
        by_commit = {}
        oldest_time = None
        newest_time = None
        
        for file_info in files:
            # File size
            filepath = os.path.join(self.project_root, file_info['filepath'])
            try:
                # Single stat call to avoid TOCTOU
                stat = os.stat(filepath)
                total_size += stat.st_size
            except (FileNotFoundError, OSError):
                # File doesn't exist or we can't access it
                pass
            
            # Group by commit
            commit = file_info.get('commit_hash', 'unknown')
            by_commit[commit] = by_commit.get(commit, 0) + 1
            
            # Track timestamps
            queued_at = file_info.get('queued_at')
            if queued_at:
                if not oldest_time or queued_at < oldest_time:
                    oldest_time = queued_at
                if not newest_time or queued_at > newest_time:
                    newest_time = queued_at
        
        return {
            'status': 'active',
            'queued_files': len(files),
            'total_size': total_size,
            'oldest_entry': oldest_time,
            'newest_entry': newest_time,
            'by_commit': by_commit
        }
    
    def list_queued_files(self, limit: Optional[int] = None) -> List[Dict]:
        """List files currently in the queue."""
        queue_data = self._load_queue()
        if not queue_data:
            return []
        
        files = queue_data.get('files', [])
        
        # Sort by queued_at time (oldest first)
        files.sort(key=lambda f: f.get('queued_at', ''))
        
        if limit:
            files = files[:limit]
        
        # Add additional info
        result = []
        for file_info in files:
            filepath = file_info['filepath']
            full_path = os.path.join(self.project_root, filepath)
            
            info = {
                'filepath': filepath,
                'commit_hash': file_info.get('commit_hash', 'HEAD'),
                'queued_at': file_info.get('queued_at', 'unknown'),
            }
            
            try:
                # Single stat call to avoid TOCTOU
                stat = os.stat(full_path)
                info['exists'] = True
                info['size'] = stat.st_size
                info['modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except FileNotFoundError:
                info['exists'] = False
            except OSError:
                # Could be a permissions error, but we know it exists
                info['exists'] = True
                # Other fields will be missing, which is acceptable
            
            result.append(info)
        
        return result
    
    def add_files(self, files: List[Tuple[str, str]]) -> int:
        """
        Add files to the queue.
        
        Args:
            files: List of (filepath, commit_hash) tuples
            
        Returns:
            Number of files added
        """
        if not files:
            return 0
        
        with self._acquire_lock():
            queue_data = self._load_queue() or {'files': []}
            existing_files = {f['filepath'] for f in queue_data['files']}
            
            added = 0
            timestamp = datetime.now().isoformat()
            
            for filepath, commit_hash in files:
                if filepath not in existing_files:
                    queue_data['files'].append({
                        'filepath': filepath,
                        'commit_hash': commit_hash,
                        'queued_at': timestamp
                    })
                    added += 1
            
            if added > 0:
                self._save_queue(queue_data)
            
            return added
    
    def remove_files(self, filepaths: List[str]) -> int:
        """
        Remove specific files from the queue.
        
        Args:
            filepaths: List of file paths to remove
            
        Returns:
            Number of files removed
        """
        if not filepaths:
            return 0
        
        with self._acquire_lock():
            queue_data = self._load_queue()
            if not queue_data:
                return 0
            
            original_count = len(queue_data['files'])
            filepath_set = set(filepaths)
            
            queue_data['files'] = [
                f for f in queue_data['files'] 
                if f['filepath'] not in filepath_set
            ]
            
            removed = original_count - len(queue_data['files'])
            
            if removed > 0:
                self._save_queue(queue_data)
                self._add_to_history('removed', removed, filepaths)
            
            return removed
    
    def clear_queue(self) -> int:
        """
        Clear all files from the queue.
        
        Returns:
            Number of files cleared
        """
        with self._acquire_lock():
            queue_data = self._load_queue()
            if not queue_data:
                return 0
            
            cleared = len(queue_data.get('files', []))
            
            if cleared > 0:
                self._save_queue({'files': []})
                self._add_to_history('cleared', cleared)
            
            return cleared
    
    def process_next_batch(self, batch_size: int = 10) -> List[Dict]:
        """
        Atomically get and remove the next batch of files for processing.
        
        Args:
            batch_size: Maximum number of files to return
            
        Returns:
            List of file info dicts
        """
        with self._acquire_lock():
            queue_data = self._load_queue()
            if not queue_data:
                return []
            
            files = queue_data.get('files', [])
            if not files:
                return []
            
            # Take the first batch_size files
            batch = files[:batch_size]
            remaining = files[batch_size:]
            
            # Update queue
            queue_data['files'] = remaining
            self._save_queue(queue_data)
            
            self._add_to_history('processed_batch', len(batch))
            
            return batch
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """Get queue operation history."""
        if not os.path.exists(self.history_file):
            return []
        
        try:
            with open(self.history_file, 'r') as f:
                history = json.load(f)
                entries = history.get('entries', [])
                # Return most recent first
                entries.reverse()
                return entries[:limit]
        except (json.JSONDecodeError, IOError):
            return []
    
    def cleanup_missing_files(self) -> Tuple[int, List[str]]:
        """
        Remove queue entries for files that no longer exist.
        
        Returns:
            Tuple of (number cleaned, list of cleaned filepaths)
        """
        with self._acquire_lock():
            queue_data = self._load_queue()
            if not queue_data:
                return 0, []
            
            original_files = queue_data.get('files', [])
            valid_files = []
            removed_files = []
            
            for file_info in original_files:
                filepath = file_info['filepath']
                full_path = os.path.join(self.project_root, filepath)
                
                if os.path.exists(full_path):
                    valid_files.append(file_info)
                else:
                    removed_files.append(filepath)
            
            if removed_files:
                queue_data['files'] = valid_files
                self._save_queue(queue_data)
                self._add_to_history('cleanup_missing', len(removed_files), removed_files)
            
            return len(removed_files), removed_files
    
    def _load_queue(self) -> Optional[Dict]:
        """Load queue data from file."""
        if not os.path.exists(self.queue_file):
            return None
        
        try:
            with open(self.queue_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def _save_queue(self, data: Dict):
        """Save queue data atomically."""
        temp_file = self.queue_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Atomic replace
        os.replace(temp_file, self.queue_file)
    
    def _acquire_lock(self):
        """Context manager for acquiring queue lock."""
        class LockContext:
            def __init__(self, lock_file):
                self.lock_file = lock_file
                self.lock_fd = None
            
            def __enter__(self):
                self.lock_fd = open(self.lock_file, 'w')
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX)
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.lock_fd:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                    self.lock_fd.close()
        
        return LockContext(self.lock_file)
    
    def _add_to_history(self, operation: str, count: int, details: Optional[List[str]] = None):
        """Add an operation to history."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'count': count
        }
        
        if details:
            # Truncate details if the list is long, but always record that there were details
            entry['details'] = details[:10]  # Store up to 10 items
        
        try:
            # Load existing history
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    history = json.load(f)
            else:
                history = {'entries': []}
            
            # Add new entry
            history['entries'].append(entry)
            
            # Keep only last 1000 entries
            if len(history['entries']) > 1000:
                history['entries'] = history['entries'][-1000:]
            
            # Save
            temp_file = self.history_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(history, f, indent=2)
            
            os.replace(temp_file, self.history_file)
            
        except (IOError, json.JSONDecodeError) as e:
            # Don't fail operations due to history errors, but make the problem visible
            logging.warning(f"Could not write to queue history file: {e}")