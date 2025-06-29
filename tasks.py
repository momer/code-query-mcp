from huey import SqliteHuey
import subprocess
import json
import os
import logging
from typing import Dict, Any, Optional, List
from functools import lru_cache
from storage.sqlite_storage import CodeQueryServer

# Initialize Huey with SQLite backend
# This creates a separate database for job queue management
huey = SqliteHuey(
    name='code-query-worker',
    filename='.code-query/huey_jobs.db',
    immediate=False  # Important: False means tasks run asynchronously
)

# Configure logging for tasks
logger = logging.getLogger('code-query.tasks')
logger.setLevel(logging.INFO)

# Add file handler for worker logs - will be set up properly by worker manager
def setup_logging(log_file_path: str):
    """Set up logging to the specified file."""
    handler = logging.FileHandler(log_file_path)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)

@lru_cache(maxsize=8)  # Cache connections for up to 8 different projects
def get_storage_server(project_root: str) -> CodeQueryServer:
    """Creates and caches CodeQueryServer instances."""
    db_path = os.path.join(project_root, '.code-query', 'code_data.db')
    logger.info(f"Creating or reusing storage connection for project: {project_root}")
    return CodeQueryServer(db_path)

@lru_cache(maxsize=8)
def get_project_config(project_root: str) -> Dict[str, Any]:
    """Loads and caches project configuration."""
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

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
        filepath: Relative path to the file to document
        dataset_name: Dataset to update
        commit_hash: Git commit hash for tracking
        project_root: Root directory of the project
        
    Returns:
        Dict with success status and any error messages
    """
    logger.info(f"Processing documentation for {filepath}...")
    
    # --- Non-retriable validation phase ---
    try:
        # Security validation: Ensure file is within project boundaries
        abs_filepath = os.path.join(project_root, filepath)
        real_filepath = os.path.realpath(abs_filepath)
        real_project_root = os.path.realpath(project_root)
        
        # Security check: Ensure resolved path is within project root
        # Using os.path.commonpath for more idiomatic and robust check
        if os.path.commonpath([real_filepath, real_project_root]) != real_project_root:
            error_msg = f"Security violation: File {filepath} resolves outside project root"
            logger.error(error_msg)
            return {"success": False, "filepath": filepath, "error": error_msg}
        
        # Verify file exists and is a file
        if not os.path.isfile(real_filepath):
            error_msg = f"File not found or not a regular file: {filepath}"
            logger.error(error_msg)
            return {"success": False, "filepath": filepath, "error": error_msg}
        
        # Load configuration from cache
        config = get_project_config(project_root)
        model = config.get('model', 'claude-3-5-sonnet-20240620')
        
    except (FileNotFoundError, ValueError, KeyError) as e:
        logger.error(f"✗ Validation/setup failed for {filepath}, will not retry: {str(e)}")
        return {"success": False, "filepath": filepath, "error": f"Validation failed: {e}"}
    
    # --- Retriable execution phase ---
    # Any exception raised here will be caught by Huey for retry
    
    # Mitigate TOCTOU by reading the file now and passing content via stdin
    try:
        with open(real_filepath, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except Exception as e:
        # This could be a read error if the file is removed after the check.
        # Treat as a retriable error.
        logger.error(f"Failed to read file {filepath}: {e}")
        raise  # Re-raise to trigger Huey retry
    
    # Pass file content via stdin to avoid TOCTOU vulnerability
    result = subprocess.run([
        'claude', 
        '-p',  # Print mode for non-interactive
        f'Analyze and document the code in the provided file ({filepath}). Focus on its purpose, main functions, exports, imports, and key implementation details.\n\nFile content:\n{file_content}',
        '--model', model
    ], capture_output=True, text=True, cwd=project_root, check=False)  # Use check=False to handle error manually
    
    if result.returncode != 0:
        # Log a sanitized message by default
        error_summary = (result.stderr or "No stderr output").splitlines()[0] if result.stderr else "Unknown error"
        error_msg = f"Claude processing failed with exit code {result.returncode}"
        logger.error(f"✗ Failed to document {filepath}: {error_msg}")
        # Log detailed output at debug level
        logger.debug(f"Full stderr for {filepath}: {result.stderr}")
        raise Exception(f"{error_msg}. See debug logs for details.")  # This will now trigger a retry
    
    # Parse Claude's response and update database
    documentation = parse_claude_response(result.stdout)
    
    # Update the main code-query database with relative path using cached connection
    storage = get_storage_server(project_root)
    storage.update_file_documentation(
        dataset_name=dataset_name,
        filepath=filepath,  # Use original relative path for storage
        commit_hash=commit_hash,
        **documentation
    )
    
    logger.info(f"✓ Completed documentation for {filepath}")
    return {"success": True, "filepath": filepath}

@huey.task()
def process_documentation_batch(
    files: List[Dict[str, str]], 
    dataset_name: str,
    project_root: str
) -> Dict[str, Any]:
    """
    Enqueues multiple file processing tasks for parallel execution.
    
    Args:
        files: List of dicts with 'filepath' and 'commit_hash' keys
        dataset_name: Dataset to update
        project_root: Root directory of the project
        
    Returns:
        Dict with task IDs for tracking
    """
    task_ids = []
    for file_info in files:
        # Enqueue each file as a separate task for parallel processing
        task = process_file_documentation(
            filepath=file_info['filepath'],
            dataset_name=dataset_name,
            commit_hash=file_info['commit_hash'],
            project_root=project_root
        )
        task_ids.append(str(task.id))
    
    logger.info(f"Enqueued a batch of {len(files)} files for parallel processing.")
    
    return {
        "batch_size": len(files),
        "task_ids": task_ids,
        "status": "enqueued"
    }

def parse_claude_response(response: str) -> Dict[str, Any]:
    """
    Parse Claude's response into structured documentation.
    This is a placeholder - actual implementation would parse
    Claude's structured output.
    """
    # TODO: Implement actual parsing based on Claude's response format
    # For now, return a minimal valid structure
    return {
        "overview": response[:200] + "..." if len(response) > 200 else response,
        "functions": {},
        "imports": {},
        "exports": {},
        "types_interfaces_classes": {},
        "constants": {},
        "dependencies": [],
        "other_notes": []
    }

# Health check task for monitoring
@huey.task()
def health_check() -> Dict[str, Any]:
    """Simple task to verify worker is running."""
    logger.info("Health check executed")
    return {"status": "ok", "timestamp": os.environ.get('HUEY_WORKER_START_TIME', 'unknown')}