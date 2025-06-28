#!/usr/bin/env python3
import os
import sys
import json
import time
import fcntl
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class GitHookHandler:
    """Handles git hook logic for code-query documentation updates."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.config_path = os.path.join(project_root, '.code-query', 'config.json')
        self.queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
        self.pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
        self.lock_file = os.path.join(project_root, '.code-query', 'queue.lock')
    
    def handle_post_commit(self) -> int:
        """
        Handle post-commit hook logic.
        
        Returns:
            int: Exit code (0 for success, non-zero for error)
        """
        try:
            # Load configuration
            config = self._load_config()
            if not config:
                print("⚠️  Code-query not configured. Run: python server.py worker setup")
                return 0  # Don't block commit
            
            # Get processing mode
            processing_config = config.get('processing', {})
            mode = processing_config.get('mode', 'manual')
            fallback_to_sync = processing_config.get('fallback_to_sync', True)
            
            # Atomically get and clear queued files
            queued_files = self._atomic_read_and_clear_queue()
            if not queued_files:
                # No files to process or another hook is handling them
                return 0
            
            print(f"\n📄 Processing {len(queued_files)} file(s) for documentation...")
            
            # Decide sync vs async
            if mode == 'manual':
                # Always process synchronously
                return self._process_synchronously(queued_files, config)
            
            elif mode == 'auto':
                # Check if worker is running
                if self._is_worker_running():
                    # Enqueue to Huey
                    return self._enqueue_to_huey(queued_files, config)
                else:
                    # Worker not running
                    if fallback_to_sync:
                        print("⚠️  Background worker not running, processing synchronously...")
                        print("  💡 Start worker with: python server.py worker start")
                        return self._process_synchronously(queued_files, config)
                    else:
                        print("✗ Background worker not running")
                        print("  💡 Start worker with: python server.py worker start")
                        print("  💡 Or enable fallback: python server.py worker config --fallback")
                        # Don't process, but don't fail the commit
                        return 0
            
        except Exception as e:
            print(f"✗ Hook error: {e}")
            # Never block commits due to hook errors
            return 0
    
    def _load_config(self) -> Optional[Dict]:
        """Load configuration file."""
        if not os.path.exists(self.config_path):
            return None
        
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️  Error loading config: {e}")
            return None
    
    def _atomic_read_and_clear_queue(self) -> List[Dict[str, str]]:
        """Atomically reads and clears the queue to prevent race conditions."""
        if not os.path.exists(self.queue_file):
            return []
        
        # Ensure lock directory exists
        os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
        
        try:
            with open(self.lock_file, 'w') as lf:
                # Acquire exclusive non-blocking lock
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # If we got the lock, read and immediately clear
                queued_files = self._load_queue_snapshot()
                if queued_files:
                    self._clear_queue()
                
                fcntl.flock(lf, fcntl.LOCK_UN)
                return queued_files
                
        except (IOError, BlockingIOError):
            # Another process has the lock
            print("ℹ️  Another commit is being processed. This commit's changes will be handled next.")
            return []
    
    def _load_queue_snapshot(self) -> List[Dict[str, str]]:
        """
        Load and snapshot the current queue.
        This prevents race conditions with concurrent commits.
        """
        if not os.path.exists(self.queue_file):
            return []
        
        try:
            with open(self.queue_file, 'r') as f:
                data = json.load(f)
                return data.get('files', [])
        except (json.JSONDecodeError, IOError):
            return []
    
    def _is_worker_running(self) -> bool:
        """Check if the background worker is running."""
        if not os.path.exists(self.pid_file):
            return False
        
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Use basic os.kill with signal 0 to check if process exists
            # This works cross-platform without requiring psutil in hooks
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                # Process doesn't exist
                return False
                
        except (ValueError, IOError):
            return False
    
    def _process_synchronously(self, files: List[Dict[str, str]], config: Dict) -> int:
        """
        Process files synchronously during the commit.
        
        Args:
            files: List of file info dicts with 'filepath' and 'commit_hash'
            config: Configuration dictionary
            
        Returns:
            int: Exit code
        """
        import subprocess
        
        dataset_name = config.get('dataset_name', 'default')
        model = config.get('model', 'claude-3-5-sonnet-20240620')
        
        completed = []
        failed = []
        
        for file_info in files:
            filepath = file_info['filepath']
            
            # Validate file path to prevent traversal attacks
            abs_project_root = os.path.abspath(self.project_root)
            abs_filepath = os.path.abspath(os.path.join(abs_project_root, filepath))
            
            if not abs_filepath.startswith(abs_project_root + os.sep):
                print(f"  Processing {filepath}... ✗ (Security: Attempted to access file outside project root)")
                failed.append(file_info)
                continue
            
            commit_hash = file_info.get('commit_hash', 'HEAD')
            
            print(f"  Processing {filepath}...", end='', flush=True)
            
            try:
                # Call code-query MCP to update documentation
                result = subprocess.run([
                    sys.executable, 'server.py',
                    'document-file',
                    '--dataset', dataset_name,
                    '--file', filepath,
                    '--commit', commit_hash,
                    '--model', model
                ], capture_output=True, text=True, cwd=self.project_root)
                
                if result.returncode == 0:
                    print(" ✓")
                    completed.append(file_info)
                else:
                    print(f" ✗ ({result.stderr.strip()})")
                    failed.append(file_info)
                    
            except Exception as e:
                print(f" ✗ ({e})")
                failed.append(file_info)
        
        # Queue already cleared atomically, no need to update
        
        # Summary
        print(f"\n✓ Documentation updated ({len(completed)} files processed)")
        if failed:
            print(f"⚠️  {len(failed)} file(s) failed to process")
            # Could re-queue failed files here if desired
        
        return 0
    
    def _enqueue_to_huey(self, files: List[Dict[str, str]], config: Dict) -> int:
        """
        Enqueue files to Huey for background processing.
        
        Args:
            files: List of file info dicts
            config: Configuration dictionary
            
        Returns:
            int: Exit code
        """
        try:
            # Import Huey and our tasks
            sys.path.insert(0, self.project_root)
            from tasks import process_file_documentation, huey
            
            dataset_name = config.get('dataset_name', 'default')
            
            # Enqueue each file
            task_ids = []
            for file_info in files:
                task = process_file_documentation(
                    filepath=file_info['filepath'],
                    dataset_name=dataset_name,
                    commit_hash=file_info.get('commit_hash', 'HEAD'),
                    project_root=self.project_root
                )
                task_ids.append(task.id)
            
            # Queue already cleared atomically
            
            print(f"✓ {len(files)} file(s) queued for background processing")
            print(f"  Monitor progress: tail -f {os.path.join(self.project_root, '.code-query', 'worker.log')}")
            
            return 0
            
        except ImportError as e:
            print(f"⚠️  Failed to import Huey tasks: {e}")
            print("  Falling back to synchronous processing...")
            return self._process_synchronously(files, config)
        except Exception as e:
            print(f"⚠️  Failed to enqueue tasks: {e}")
            print("  Falling back to synchronous processing...")
            return self._process_synchronously(files, config)
    
    def _update_queue(self, completed_files: List[Dict[str, str]]):
        """Remove completed files from the queue atomically."""
        if not completed_files:
            return
        
        # Load current queue
        current_queue = self._load_queue_snapshot()
        
        # Filter out completed files
        completed_paths = {f['filepath'] for f in completed_files}
        remaining = [f for f in current_queue if f['filepath'] not in completed_paths]
        
        # Write updated queue atomically
        temp_file = self.queue_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump({'files': remaining}, f, indent=2)
        
        os.replace(temp_file, self.queue_file)
    
    def _clear_queue(self):
        """Clear the entire queue."""
        temp_file = self.queue_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump({'files': []}, f, indent=2)
        
        os.replace(temp_file, self.queue_file)


def handle_post_commit() -> int:
    """Entry point for post-commit hook."""
    # Get git repository root
    import subprocess
    result = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        return 1
    
    project_root = result.stdout.strip()
    handler = GitHookHandler(project_root)
    return handler.handle_post_commit()


if __name__ == '__main__':
    sys.exit(handle_post_commit())