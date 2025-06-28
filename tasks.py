from huey import SqliteHuey
import subprocess
import json
import os
import logging
from typing import Dict, Any, Optional, List
from storage.sqlite_storage import CodeQueryServer

# Configure logging at module level for Huey consumer
log_dir = os.path.join(os.getcwd(), '.code-query')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'worker.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()  # Also log to console
    ]
)

logger = logging.getLogger('code-query.tasks')

# Define a reasonable limit for batch processing
MAX_BATCH_SIZE = 1000

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
    logger.info(f"Processing documentation for {filepath}...")
    
    try:
        # Load configuration
        config_path = os.path.join(project_root, '.code-query', 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        model = config.get('model', 'claude-3-5-sonnet-20240620')
        
        # Construct absolute file path
        abs_filepath = os.path.join(project_root, filepath)
        
        # Security: Prevent path traversal attacks
        resolved_project_root = os.path.realpath(project_root)
        resolved_filepath = os.path.realpath(abs_filepath)
        
        # Ensure the root path ends with a separator for a robust check
        # This prevents matching '/app/project_evil' if root is '/app/project'
        safe_project_root = os.path.join(resolved_project_root, '')
        
        if not resolved_filepath.startswith(safe_project_root):
            error_msg = f"Security violation: Attempted to access file outside of project root: {filepath}"
            logger.error(error_msg)
            # Do not retry this, it's a permanent failure
            return {"success": False, "filepath": filepath, "error": error_msg}
        
        # Call Claude to analyze the file
        result = subprocess.run([
            'claude', 
            '--prompt', f'Analyze and document the code in {resolved_filepath}. Focus on its purpose, main functions, exports, imports, and key implementation details.',
            '--model', model,
            '--file', resolved_filepath
        ], capture_output=True, text=True, cwd=project_root)
        
        if result.returncode == 0:
            # Parse Claude's response and update database
            documentation = parse_claude_response(result.stdout)
            
            # Update the main code-query database
            db_path = os.path.join(project_root, '.code-query', 'code_data.db')
            db_dir = os.path.join(project_root, '.code-query')
            storage = CodeQueryServer(db_path, db_dir)
            storage.update_file_documentation(
                dataset_name=dataset_name,
                filepath=filepath,
                commit_hash=commit_hash,
                **documentation
            )
            
            logger.info(f"✓ Completed documentation for {filepath}")
            return {"success": True, "filepath": filepath}
        else:
            # This is a retriable error. Raise an exception to trigger Huey's retry.
            error_msg = f"Claude processing failed with exit code {result.returncode}: {result.stderr}"
            logger.error(f"✗ Failed to document {filepath}: {error_msg}. Will retry.")
            raise Exception(error_msg)
            
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # Non-retriable error: config/file not found or config is corrupt
        logger.error(f"✗ Non-retriable error for {filepath}: {e}")
        return {"success": False, "filepath": filepath, "error": f"Non-retriable error: {e}"}
    except Exception as e:
        # Let other exceptions propagate for retry
        logger.error(f"✗ Unexpected error processing {filepath}: {e}")
        raise

@huey.task()
def process_documentation_batch(
    files: List[Dict[str, str]], 
    dataset_name: str,
    project_root: str
) -> Dict[str, Any]:
    """
    Enqueue multiple files for processing.
    Each file is enqueued as a separate task for parallel processing.
    """
    if len(files) > MAX_BATCH_SIZE:
        logger.warning(f"Batch size {len(files)} exceeds limit of {MAX_BATCH_SIZE}. Rejecting.")
        return {
            "status": "rejected",
            "error": f"Batch size exceeds limit of {MAX_BATCH_SIZE}"
        }
    
    logger.info(f"Enqueuing batch of {len(files)} files for processing.")
    
    for file_info in files:
        # Enqueue each file as a separate task
        process_file_documentation(
            filepath=file_info['filepath'],
            dataset_name=dataset_name,
            commit_hash=file_info['commit_hash'],
            project_root=project_root
        )
    
    return {
        "status": "enqueued",
        "count": len(files)
    }

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

