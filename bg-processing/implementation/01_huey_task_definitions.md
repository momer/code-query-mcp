# Step 1: Huey Task Definitions

## Overview
Create the core Huey task definitions for processing documentation updates in the background.

## References
- phase1_pr_plan.md:141-173
- automated_queue_processing_plan.md:141-173

## Implementation Tasks

### 1.1 Create tasks.py file
**Location**: `tasks.py` (root level for Huey discovery)

```python
from huey import SqliteHuey
import subprocess
import json
import os
from typing import Dict, Any, Optional
from storage.sqlite_storage import SQLiteStorage

# Initialize Huey with SQLite backend
# This creates a separate database for job queue management
huey = SqliteHuey(
    name='code-query-worker',
    filename='.code-query/huey_jobs.db',
    immediate=False  # Important: False means tasks run asynchronously
)

@huey.task(retries=2, retry_delay=60)
def process_file_documentation(
    filepath: str, 
    dataset_name: str, 
    commit_hash: str,
    project_root: str
) -> Dict[str, Any]:
    """
    Background task that calls claude and updates documentation.
    
    Args:
        filepath: Path to the file to document
        dataset_name: Dataset to update
        commit_hash: Git commit hash for tracking
        project_root: Root directory of the project
        
    Returns:
        Dict with success status and any error messages
    """
    print(f"[TASK] Processing documentation for {filepath}...")
    
    try:
        # Load configuration
        config_path = os.path.join(project_root, '.code-query', 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        model = config.get('model', 'claude-3-5-sonnet-20240620')
        
        # Construct absolute file path
        abs_filepath = os.path.join(project_root, filepath)
        
        # Call Claude to analyze the file
        result = subprocess.run([
            'claude', 
            '--prompt', f'Analyze and document the code in {filepath}. Focus on its purpose, main functions, exports, imports, and key implementation details.',
            '--model', model,
            '--file', abs_filepath
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0:
            # Parse Claude's response and update database
            documentation = parse_claude_response(result.stdout)
            
            # Update the main code-query database
            storage = SQLiteStorage(os.path.join(project_root, '.code-query', 'code_data.db'))
            storage.update_file_documentation(
                dataset_name=dataset_name,
                filepath=filepath,
                commit_hash=commit_hash,
                **documentation
            )
            
            print(f"[TASK] ✓ Completed documentation for {filepath}")
            return {"success": True, "filepath": filepath}
        else:
            error_msg = f"Claude processing failed: {result.stderr}"
            print(f"[TASK] ✗ Failed to document {filepath}: {error_msg}")
            raise Exception(error_msg)
            
    except Exception as e:
        print(f"[TASK] ✗ Error processing {filepath}: {str(e)}")
        return {"success": False, "filepath": filepath, "error": str(e)}

def parse_claude_response(response: str) -> Dict[str, Any]:
    """
    Parse Claude's response into structured documentation.
    This is a placeholder - actual implementation would parse
    Claude's structured output.
    """
    # TODO: Implement actual parsing based on Claude's response format
    return {
        "overview": response[:200] + "...",  # Placeholder
        "functions": {},
        "imports": {},
        "exports": {},
        "types_interfaces_classes": {},
        "constants": {},
        "dependencies": [],
        "other_notes": []
    }
```

### 1.2 Add logging configuration

```python
import logging
from huey.contrib.mini import MiniHuey

# Configure logging for tasks
logger = logging.getLogger('code-query.tasks')
logger.setLevel(logging.INFO)

# Add file handler for worker logs
handler = logging.FileHandler('.code-query/worker.log')
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(handler)

# Use logger in tasks instead of print
@huey.task(retries=2, retry_delay=60)
def process_file_documentation(...):
    logger.info(f"Processing documentation for {filepath}...")
    # ... rest of implementation
```

### 1.3 Add batch processing task

```python
@huey.task()
def process_documentation_batch(
    files: List[Dict[str, str]], 
    dataset_name: str,
    project_root: str
) -> Dict[str, Any]:
    """
    Process multiple files as a batch.
    Useful for reducing overhead when processing many files.
    """
    results = []
    for file_info in files:
        result = process_file_documentation(
            filepath=file_info['filepath'],
            dataset_name=dataset_name,
            commit_hash=file_info['commit_hash'],
            project_root=project_root
        )
        results.append(result)
    
    successful = sum(1 for r in results if r.get('success', False))
    logger.info(f"Batch complete: {successful}/{len(files)} files processed successfully")
    
    return {
        "total": len(files),
        "successful": successful,
        "results": results
    }
```

## Testing Checklist
- [ ] Huey initializes with correct SQLite backend
- [ ] Tasks can be imported without errors
- [ ] process_file_documentation handles all parameters
- [ ] Retry logic works on failures
- [ ] Logging outputs to worker.log
- [ ] Path handling works with project_root parameter

## Integration Notes
- Tasks must be importable by huey_consumer
- SQLite database path must be relative to project root
- All file paths should be handled relative to project_root
- Consider memory usage for large files