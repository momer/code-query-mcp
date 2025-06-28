# Phase 1 PR Plan: Core Queue Processing

## PR Title
feat: Add background queue processing with Huey for automated documentation updates

## PR Description
This PR implements the foundation for automated queue processing in code-query MCP. It introduces Huey as a lightweight task queue with SQLite backend, enabling git hooks to queue documentation updates for background processing while maintaining synchronous fallback for excellent developer experience.

## Changes Overview

### 1. New Dependencies
- Add `huey` and `psutil` to requirements.txt
- Update installation documentation
- Note: No shell dependencies (jq) required - hooks are pure Python

### 2. Task Queue Module (`queue/tasks.py`)
```python
# New file structure:
queue/
├── __init__.py
├── tasks.py          # Huey task definitions
├── worker.py         # Worker management utilities
└── sync_processor.py # Synchronous fallback processor
```

### 3. Worker Detection (`helpers/worker_detector.py`)
- Process-based detection using psutil
- Standalone script for git hook usage
- Integration with main codebase

### 4. Configuration Extensions
- Extend `storage/config_manager.py` to handle processing config
- Add processing section to config schema
- Default values for graceful degradation

### 5. Git Hook Enhancements
- Update `helpers/git_helper.py` to generate Python-based hooks
- Add mode detection (auto/manual)
- Implement fallback logic
- Create `helpers/git_hook_handler.py` for hook logic

### 6. CLI Command Extensions (`cli/worker_commands.py`)
- Add worker subcommand to server.py
- Implement start/stop/status commands
- Basic worker lifecycle management

### 7. Queue Processing Scripts
```
.code-query/
├── check_worker.py      # Standalone worker detection
├── enqueue_tasks.py     # Queue file updates
└── process_sync.py      # Synchronous processor
```

#### Example `enqueue_tasks.py`:
```python
#!/usr/bin/env python3
import os
import json
import sys


def main():
    """Main entry point for enqueue_tasks script"""
    # Add parent directory to path to import queue module
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from queue.tasks import process_file_documentation
    
    # Get project root (current working directory)
    project_root = os.getcwd()
    
    # Load queued files
    queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
    config_file = os.path.join(project_root, '.code-query', 'config.json')
    
    with open(queue_file, 'r') as f:
        queue_data = json.load(f)
    
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    dataset_name = config.get('dataset_name', 'default')
    
    # Enqueue each file
    for item in queue_data.get('files', []):
        filepath = item['filepath']
        commit_hash = item.get('commit_hash')
        
        # Pass project_root to ensure task can find config
        process_file_documentation(
            filepath=filepath,
            dataset_name=dataset_name,
            project_root=project_root,
            commit_hash=commit_hash
        )
    
    print(f"✓ Queued {len(queue_data.get('files', []))} files for processing")
    
    # Clear the queue file
    with open(queue_file, 'w') as f:
        json.dump({'files': []}, f)


if __name__ == "__main__":
    main()
```

## Implementation Details

### File Changes

#### 1. `requirements.txt`
```diff
+ huey==2.5.0
+ psutil==5.9.5
```

#### 2. `queue/tasks.py`
```python
from huey import SqliteHuey
import subprocess
import json
import os
from pathlib import Path
from typing import Optional
from storage.sqlite_storage import SQLiteStorage

# Initialize Huey with SQLite backend
huey = SqliteHuey(
    name='code-query-worker',
    filename='.code-query/huey_jobs.db',
    immediate=False
)

@huey.task(retries=2, retry_delay=60)
def process_file_documentation(
    filepath: str, 
    dataset_name: str, 
    project_root: str,  # Required for finding config
    commit_hash: Optional[str] = None
):
    """Process a single file's documentation update"""
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    
    # Load configuration from absolute path
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    model = config.get('model', 'claude-3-5-sonnet-20240620')
    
    # Call Claude to analyze the file
    result = subprocess.run([
        'claude', '--prompt', f'Analyze and document {filepath}', 
        '--model', model
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        # Update the main code-query database
        storage_path = os.path.join(project_root, '.code-query', 'code_data.db')
        storage = SQLiteStorage(storage_path)
        # Parse result and update documentation
        print(f"✓ Completed documentation for {filepath}")
    else:
        print(f"✗ Failed to document {filepath}: {result.stderr}")
        raise Exception(f"Claude processing failed: {result.stderr}")
```

#### 3. `helpers/worker_detector.py`
```python
import os
import psutil
from typing import Tuple, Optional

PID_FILE = ".code-query/worker.pid"

def is_worker_running() -> Tuple[bool, Optional[int]]:
    """
    Check if worker is running by checking PID file and verifying process
    Returns: (is_running, pid)
    """
    if not os.path.exists(PID_FILE):
        return False, None
    
    try:
        with open(PID_FILE, 'r') as f:
            pid_str = f.read().strip()
            if not pid_str:
                return False, None
            pid = int(pid_str)

        if psutil.pid_exists(pid):
            return True, pid

        # Process not running, clean up stale PID file
        os.remove(PID_FILE)
        return False, None
    except (ValueError, OSError):
        return False, None
```

#### 4. `storage/config_manager.py` (additions)
```python
DEFAULT_PROCESSING_CONFIG = {
    "mode": "manual",
    "worker_command": "huey_consumer queue.tasks.huey",
    "check_interval": 5,
    "fallback_to_sync": True,
    "batch_size": 5,
    "delay_seconds": 300,
    "max_retries": 2
}

def get_processing_config(self) -> dict:
    """Get processing configuration with defaults"""
    config = self.get_config()
    return config.get('processing', DEFAULT_PROCESSING_CONFIG)
```

#### 5. `cli/worker_commands.py`
```python
import subprocess
import sys
import os
import signal
from helpers.worker_detector import is_worker_running, PID_FILE

class WorkerManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.log_file = ".code-query/worker.log"
        
    def start(self):
        """Start the background worker with PID file management"""
        running, pid = is_worker_running()
        if running:
            print(f"Worker already running (PID: {pid})")
            return
            
        # Ensure .code-query directory exists
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        
        # Start huey consumer with proper logging
        cmd = [sys.executable, '-m', 'huey_consumer', 'queue.tasks.huey']
        
        with open(self.log_file, 'ab') as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=log,
                start_new_session=True
            )
        
        # Write PID file
        with open(PID_FILE, 'w') as f:
            f.write(str(process.pid))
            
        print(f"Worker started (PID: {process.pid})")
        print(f"Logs: {self.log_file}")
        
    def stop(self):
        """Stop the background worker using PID file"""
        if not os.path.exists(PID_FILE):
            print("Worker not running (no PID file found)")
            return
        
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
                
            os.kill(pid, signal.SIGTERM)
            print(f"Sent stop signal to worker (PID: {pid})")
        except ProcessLookupError:
            print(f"Worker with PID {pid} not found (may have already stopped)")
        except (ValueError, OSError) as e:
            print(f"Error stopping worker: {e}")
        finally:
            # Clean up PID file
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
        
    def status(self):
        """Check worker status"""
        running, pid = is_worker_running()
        if running:
            print(f"✓ Worker is running (PID: {pid})")
            if os.path.exists(self.log_file):
                print(f"  Logs: {self.log_file}")
        else:
            print("✗ Worker is not running")
            print("  Start with: python server.py worker start")
```

#### 6. Python Git Hook Handler (`helpers/git_hook_handler.py`)
```python
#!/usr/bin/env python3
"""
Git hook handler for code-query MCP.
Handles both pre-commit and post-commit hooks with proper error handling.
"""
import os
import sys
import json
import subprocess
from typing import Dict, List, Optional


def load_config(config_path: str) -> Optional[Dict]:
    """Load configuration file with error handling"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"WARNING: code-query config not found at '{config_path}'. Skipping hook.", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in config file: {e}", file=sys.stderr)
        return None


def check_worker_running() -> bool:
    """Check if background worker is running"""
    try:
        # Import and use the worker detector
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from helpers.worker_detector import is_worker_running
        running, _ = is_worker_running()
        return running
    except ImportError:
        print("WARNING: Could not import worker detector. Assuming worker not running.", file=sys.stderr)
        return False


def get_changed_files() -> List[str]:
    """Get list of changed files from git"""
    try:
        # Get staged files
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only'],
            capture_output=True,
            text=True,
            check=True
        )
        files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        # Filter for relevant file types (you can customize this)
        relevant_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.go', '.rs'}
        return [f for f in files if any(f.endswith(ext) for ext in relevant_extensions)]
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get changed files: {e}", file=sys.stderr)
        return []


def handle_pre_commit() -> int:
    """Handle pre-commit hook logic"""
    project_root = os.getcwd()
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    
    # Load configuration
    config = load_config(config_path)
    if not config:
        return 0  # Skip hook if no config
    
    # Get changed files
    changed_files = get_changed_files()
    if not changed_files:
        return 0  # No relevant files changed
    
    # Save changed files to queue file
    queue_file = os.path.join(project_root, '.code-query', 'file_queue.json')
    os.makedirs(os.path.dirname(queue_file), exist_ok=True)
    
    # Get current commit hash
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True)
        commit_hash = result.stdout.strip() if result.returncode == 0 else None
    except:
        commit_hash = None
    
    # Create queue entries
    queue_data = {
        'files': [
            {'filepath': f, 'commit_hash': commit_hash}
            for f in changed_files
        ]
    }
    
    with open(queue_file, 'w') as f:
        json.dump(queue_data, f, indent=2)
    
    print(f"✓ Queued {len(changed_files)} files for documentation update", file=sys.stderr)
    
    return 0


def handle_post_commit() -> int:
    """Handle post-commit hook logic"""
    project_root = os.getcwd()
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    
    # Load configuration
    config = load_config(config_path)
    if not config:
        return 0
    
    # Get processing mode
    processing_config = config.get('processing', {})
    mode = processing_config.get('mode', 'manual')
    
    if mode == 'auto':
        if check_worker_running():
            print("✓ Queuing documentation updates for background processing...", file=sys.stderr)
            try:
                # Import and run the enqueue script
                sys.path.insert(0, os.path.join(project_root, '.code-query'))
                import enqueue_tasks
                enqueue_tasks.main()
            except Exception as e:
                print(f"ERROR: Failed to enqueue tasks: {e}", file=sys.stderr)
                return 1
        else:
            print("⚠ Worker not running, processing synchronously...", file=sys.stderr)
            print("💡 To enable background processing, run: python server.py worker start", file=sys.stderr)
            try:
                sys.path.insert(0, os.path.join(project_root, '.code-query'))
                import process_sync
                process_sync.main()
            except Exception as e:
                print(f"ERROR: Failed to process synchronously: {e}", file=sys.stderr)
                return 1
    else:
        print("✓ Processing documentation updates synchronously (manual mode)...", file=sys.stderr)
        try:
            sys.path.insert(0, os.path.join(project_root, '.code-query'))
            import process_sync
            process_sync.main()
        except Exception as e:
            print(f"ERROR: Failed to process synchronously: {e}", file=sys.stderr)
            return 1
    
    return 0


if __name__ == "__main__":
    # This module is imported by the git hooks
    pass
```

#### 7. Git Hook Templates
```python
# Pre-commit hook template
PRE_COMMIT_TEMPLATE = '''#!/usr/bin/env python3
import sys
import os
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.git_hook_handler import handle_pre_commit
sys.exit(handle_pre_commit())
'''

# Post-commit hook template  
POST_COMMIT_TEMPLATE = '''#!/usr/bin/env python3
import sys
import os
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.git_hook_handler import handle_post_commit
sys.exit(handle_post_commit())
'''
```

## Testing Strategy

### Unit Tests
1. Test worker detection accuracy
2. Test task enqueueing and processing
3. Test configuration management
4. Test fallback logic

### Integration Tests
1. End-to-end git hook → queue → process flow
2. Worker lifecycle management
3. Synchronous fallback scenarios
4. Configuration changes

### Manual Testing Checklist
- [ ] Git commit with worker running (async mode)
- [ ] Git commit without worker (fallback to sync)
- [ ] Worker start/stop/status commands
- [ ] Configuration mode changes
- [ ] Multiple file processing
- [ ] Error handling and retries

## Migration Guide
1. Update existing installations with new dependencies
2. Regenerate git hooks with enhanced template
3. Update configuration files with processing section
4. Document worker management commands

## Documentation Updates
- [ ] Update README with queue processing section
- [ ] Add worker management guide
- [ ] Update configuration documentation
- [ ] Add troubleshooting section

## Rollback Plan
If issues arise:
1. Set `processing.mode` to `"manual"` to disable async
2. Original synchronous processing remains functional
3. No database schema changes required
4. Can remove huey_jobs.db without impact

## Success Metrics
- [ ] Sub-100ms git commit times with worker running
- [ ] Successful fallback when worker unavailable
- [ ] Clear user messaging about processing mode
- [ ] No regression in synchronous processing

## Dependencies on Other Work
- None - this is the foundation PR

## Follow-up Work
- Phase 2: Service management implementation
- Phase 3: Polish and documentation

## Key Improvements from Review

Based on zen's comprehensive review, the following critical improvements have been incorporated:

### 1. **PID File-Based Worker Detection**
- Replaced inefficient process scanning with PID file mechanism
- Faster, more reliable worker detection
- Prevents race conditions and spoofing

### 2. **Python-Based Git Hooks**
- Replaced shell scripts with Python for cross-platform compatibility
- Removed jq dependency entirely
- Better error handling with Python exceptions
- Direct imports of project modules
- Easier to test and maintain

### 3. **Proper Worker Process Management**
- Worker output redirected to log file (prevents broken pipes)
- Uses `sys.executable` for correct Python interpreter
- Clean PID file lifecycle management
- Proper signal handling for stop command

### 4. **Configuration Path Independence**
- Tasks receive `project_root` parameter
- No assumptions about working directory
- Works correctly when worker starts from different locations

### 5. **Service Installation Corrections (Phase 2)**
- Uses correct Python interpreter from `sys.executable`
- Properly constructs `huey_consumer` module command
- Includes log file configuration in systemd service
- Avoids hardcoded `/usr/bin/python` path

These improvements ensure the system is production-ready, handles edge cases gracefully, and provides excellent developer experience across different environments.