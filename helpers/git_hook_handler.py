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
        # Validate and normalize project root
        self.project_root = os.path.realpath(project_root)
        if not os.path.isdir(self.project_root):
            raise ValueError(f"Invalid project root: {project_root}")
        
        # Define paths securely
        self.code_query_dir = os.path.join(self.project_root, '.code-query')
        self.config_path = os.path.join(self.code_query_dir, 'config.json')
        self.queue_file = os.path.join(self.code_query_dir, 'file_queue.json')
        self.pid_file = os.path.join(self.code_query_dir, 'worker.pid')
    
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
                print("⚠️  Code-query not configured. Run: python cli.py worker setup")
                return 0  # Don't block commit
            
            # Get processing mode
            processing_config = config.get('processing', {})
            mode = processing_config.get('mode', 'manual')
            fallback_to_sync = processing_config.get('fallback_to_sync', True)
            
            # Atomically load and clear the queue
            queued_files = self._load_queue_snapshot_and_clear()
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
                        print("  💡 Start worker with: python cli.py worker start")
                        return self._process_synchronously(queued_files, config)
                    else:
                        print("✗ Background worker not running")
                        print("  💡 Start worker with: python cli.py worker start")
                        print("  💡 Or enable fallback: python cli.py worker config --fallback")
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
    
    def _load_queue_snapshot_and_clear(self) -> List[Dict[str, str]]:
        """
        Atomically reads and clears the queue to prevent race conditions.
        It does this by renaming the queue file, which is an atomic operation.
        """
        if not os.path.exists(self.queue_file):
            return []

        # Create a unique temporary path for the snapshot
        snapshot_path = self.queue_file + f".snapshot.{os.getpid()}.{time.time()}"
        
        try:
            # Atomically move the queue file to our snapshot path
            os.rename(self.queue_file, snapshot_path)
        except FileNotFoundError:
            # Another process beat us to it, the queue is empty.
            return []

        try:
            with open(snapshot_path, 'r') as f:
                data = json.load(f)
                return data.get('files', [])
        except (json.JSONDecodeError, IOError):
            # If the snapshot is corrupted, return an empty list.
            # The corrupted file will remain for inspection but won't be re-processed.
            return []
        finally:
            # Clean up the snapshot file after reading
            try:
                os.remove(snapshot_path)
            except OSError:
                pass  # Ignore errors if file is already gone
    
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
        
        # Handle multiple config field names for robustness
        # 'mainDatasetName' is used by create_project_config 
        # 'datasetName' and 'dataset_name' are legacy/alternative formats
        dataset_name = config.get('mainDatasetName') or config.get('datasetName') or config.get('dataset_name', 'default')
        model = config.get('model', 'claude-3-5-sonnet-20240620')
        
        completed = []
        failed = []
        
        for file_info in files:
            filepath = file_info['filepath']
            commit_hash = file_info.get('commit_hash', 'HEAD')
            
            # Security check: Ensure file is within project root
            abs_filepath = os.path.join(self.project_root, filepath)
            real_filepath = os.path.realpath(abs_filepath)
            real_project_root = os.path.realpath(self.project_root)
            
            if os.path.commonpath([real_filepath, real_project_root]) != real_project_root:
                print(f"  ⚠️  Skipping {filepath} (outside project)")
                continue
            
            print(f"  Processing {filepath}...", end='', flush=True)
            
            try:
                # Read file content to avoid TOCTOU
                with open(real_filepath, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                # Use Claude directly with content - request JSON-only output
                prompt = f"""Analyze the following code file and return ONLY a single, valid JSON object. Do not include any other text, explanations, or markdown formatting.

The JSON object must have these fields:
- overview: string (brief file description)
- functions: object (mapping function names to descriptions)
- imports: object (imported items)
- exports: object (exported items)  
- types_interfaces_classes: object (type definitions)
- constants: object (constant definitions)
- dependencies: array (external dependencies)
- other_notes: array (additional notes)

File: {filepath}
Content:
{file_content}"""
                
                result = subprocess.run([
                    'claude', '-p',
                    prompt,
                    '--model', model
                ], capture_output=True, text=True, cwd=self.project_root)
                
                if result.returncode == 0:
                    print(" ✓")
                    # Parse and save documentation
                    try:
                        # Attempt to parse the entire output as JSON
                        doc_data = json.loads(result.stdout.strip())
                        
                        # Update database
                        from storage.sqlite_storage import CodeQueryServer
                        storage = CodeQueryServer(os.path.join(self.project_root, '.code-query', 'code_data.db'))
                        storage.update_file_documentation(
                            dataset_name=dataset_name,
                            filepath=filepath,
                            commit_hash=commit_hash,
                            **doc_data
                        )
                        completed.append(file_info)
                    except json.JSONDecodeError:
                        # If direct parsing fails, try to extract JSON
                        import re
                        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', result.stdout, re.DOTALL)
                        if json_match:
                            try:
                                doc_data = json.loads(json_match.group())
                                
                                # Update database
                                from storage.sqlite_storage import CodeQueryServer
                                storage = CodeQueryServer(os.path.join(self.project_root, '.code-query', 'code_data.db'))
                                storage.update_file_documentation(
                                    dataset_name=dataset_name,
                                    filepath=filepath,
                                    commit_hash=commit_hash,
                                    **doc_data
                                )
                                completed.append(file_info)
                            except Exception as e:
                                print(f" ✗ (parse error: {e})")
                                failed.append(file_info)
                        else:
                            print(f" ✗ (invalid JSON response)")
                            failed.append(file_info)
                    except Exception as e:
                        print(f" ✗ (error: {e})")
                        failed.append(file_info)
                else:
                    print(f" ✗ (claude error)")
                    failed.append(file_info)
                    
            except Exception as e:
                print(f" ✗ ({e})")
                failed.append(file_info)
        
        # Queue was already cleared atomically, no need to update
        
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
            
            # Handle multiple config field names for robustness
            # 'mainDatasetName' is used by create_project_config 
            # 'datasetName' and 'dataset_name' are legacy/alternative formats
            dataset_name = config.get('mainDatasetName') or config.get('datasetName') or config.get('dataset_name', 'default')
            
            # Enqueue each file
            task_ids = []
            for file_info in files:
                task = process_file_documentation(
                    filepath=file_info['filepath'],
                    dataset_name=dataset_name,
                    commit_hash=file_info.get('commit_hash', 'HEAD'),
                    project_root=self.project_root
                )
                task_ids.append(str(task.id))
            
            # Queue was already cleared atomically, no need to clear again
            
            print(f"✓ {len(files)} file(s) queued for background processing")
            print(f"  Monitor progress: tail -f {os.path.join(self.project_root, '.code-query', 'logs', 'worker.log')}")
            
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


def install_git_hooks(project_root: str) -> bool:
    """
    Install or update git hooks for the project.
    
    Args:
        project_root: Path to project root
        
    Returns:
        bool: True if installation successful
    """
    # Validate project root
    real_project_root = os.path.realpath(project_root)
    git_hooks_dir = os.path.join(real_project_root, '.git', 'hooks')
    
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
        # Back up existing hook if present
        if os.path.exists(hook_path):
            backup_path = hook_path + '.backup'
            import shutil
            shutil.copy2(hook_path, backup_path)
            print(f"  Backed up existing hook to {backup_path}")
        
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


if __name__ == '__main__':
    sys.exit(handle_post_commit())