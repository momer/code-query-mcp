# Step 3: Git Hook Logic (Python Implementation)

## Overview
Implement Python-based git hooks that handle the queue processing decision (sync vs async) with proper error handling and user feedback.

## References
- phase1_pr_plan.md:97-135
- automated_queue_processing_plan.md:96-113
- Zen's feedback on queue management and sync/async decision

## Implementation Tasks

### 3.1 Create helpers/git_hook_handler.py

```python
#!/usr/bin/env python3
import os
import sys
import json
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path

class GitHookHandler:
    """Handles git hook logic for code-query documentation updates."""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.config_path = os.path.join(project_root, '.code-query', 'config.json')
        self.queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
        self.pid_file = os.path.join(project_root, '.code-query', 'worker.pid')
    
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
            
            # Load queued files (snapshot at start)
            queued_files = self._load_queue_snapshot()
            if not queued_files:
                # No files to process
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
        
        # Update queue to remove completed files
        self._update_queue(completed)
        
        # Summary
        print(f"\n✓ Documentation updated ({len(completed)} files processed)")
        if failed:
            print(f"⚠️  {len(failed)} file(s) failed to process")
        
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
            
            # Clear the queue since we've enqueued everything
            self._clear_queue()
            
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
```

### 3.2 Create Python git hook scripts

**post-commit hook** (`.git/hooks/post-commit`):
```python
#!/usr/bin/env python3
import sys
import os

# Add project root to Python path
git_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(git_dir)
sys.path.insert(0, project_root)

# Import and run handler
from helpers.git_hook_handler import handle_post_commit
sys.exit(handle_post_commit())
```

### 3.3 Add hook installation function

```python
def install_git_hooks(project_root: str) -> bool:
    """
    Install or update git hooks for the project.
    
    Args:
        project_root: Path to project root
        
    Returns:
        bool: True if installation successful
    """
    git_hooks_dir = os.path.join(project_root, '.git', 'hooks')
    
    if not os.path.exists(git_hooks_dir):
        print("✗ Not a git repository")
        return False
    
    # Post-commit hook content
    hook_content = '''#!/usr/bin/env python3
import sys
import os

# Add project root to Python path
git_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(git_dir)
sys.path.insert(0, project_root)

# Import and run handler
from helpers.git_hook_handler import handle_post_commit
sys.exit(handle_post_commit())
'''
    
    hook_path = os.path.join(git_hooks_dir, 'post-commit')
    
    try:
        # Write hook file
        with open(hook_path, 'w') as f:
            f.write(hook_content)
        
        # Make executable
        os.chmod(hook_path, 0o755)
        
        print(f"✓ Installed post-commit hook")
        return True
        
    except Exception as e:
        print(f"✗ Failed to install hook: {e}")
        return False
```

## Testing Checklist
- [ ] Post-commit hook triggers after commits
- [ ] Configuration loading handles missing/invalid files
- [ ] Queue snapshot prevents race conditions
- [ ] Worker detection works without psutil
- [ ] Sync processing completes and updates queue
- [ ] Async enqueueing works when worker is running
- [ ] Fallback to sync works when configured
- [ ] Clear user messages for all scenarios
- [ ] Hook never blocks commits (always returns 0)

## Error Handling
- Missing config: Warn but don't block
- Corrupted queue: Skip processing but don't block
- Import errors: Fall back to sync
- Any exception: Log but return 0 to avoid blocking commits