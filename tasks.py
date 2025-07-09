from huey import SqliteHuey
import subprocess
import json
import os
import logging
from typing import Dict, Any, Optional, List
from functools import lru_cache
from storage.sqlite_storage import CodeQueryServer
from analysis.analyzer import FileAnalyzer
from app.job_storage import JobStorage

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

@lru_cache(maxsize=8)
def get_job_storage(db_path: str) -> JobStorage:
    """Creates and caches JobStorage instances."""
    logger.info(f"Creating or reusing job storage connection for db: {db_path}")
    return JobStorage(db_path)

@huey.task(retries=2, retry_delay=60)
def process_file_documentation(
    filepath: str, 
    dataset_name: str, 
    commit_hash: str,
    project_root: str,
    job_id: Optional[str] = None  # Added for job tracking
) -> Dict[str, Any]:
    """
    Huey task wrapper for file documentation.
    Delegates all business logic to FileAnalyzer.
    
    Args:
        filepath: Relative path to the file to document
        dataset_name: Dataset to update
        commit_hash: Git commit hash for tracking
        project_root: Root directory of the project
        job_id: Optional job ID for progress tracking
        
    Returns:
        Dict with success status and any error messages
    """
    logger.info(f"Processing documentation for {filepath} (Job ID: {job_id})...")
    
    # Get dependencies
    storage = get_storage_server(project_root)
    config = get_project_config(project_root)
    model = config.get('model', 'sonnet')
    job_storage = get_job_storage(storage.db_path) if job_id else None
    
    # Track success and error for finally block
    success = False
    error_message = None
    
    try:
        # Use FileAnalyzer for core logic
        analyzer = FileAnalyzer(project_root, storage, model)
        result = analyzer.analyze_and_document(filepath, dataset_name, commit_hash)
        
        success = True
        logger.info(f"✓ Completed documentation for {filepath}")
        return {"success": True, "filepath": filepath, "job_id": job_id}
        
    except (PermissionError, FileNotFoundError, ValueError, KeyError) as e:
        # Non-retriable errors - don't trigger Huey retry
        error_message = str(e)
        logger.error(f"✗ Validation failed for {filepath}, will not retry: {error_message}")
        return {"success": False, "filepath": filepath, "error": error_message, "job_id": job_id}
        
    except Exception as e:
        # Retriable errors - re-raise for Huey
        error_message = str(e)
        logger.error(f"✗ Task failed for {filepath} in job {job_id}: {error_message}")
        raise
        
    finally:
        # Update job progress regardless of success/failure
        if job_id and job_storage:
            try:
                job_storage.record_file_processed(
                    job_id=job_id,
                    filepath=filepath,
                    success=success,
                    error_message=error_message,
                    huey_task_id=str(huey.task.id) if hasattr(huey, 'task') else None,
                    commit_hash=commit_hash
                )
            except Exception as e:
                logger.warning(f"Failed to update job progress for {filepath}: {e}")

@huey.task()
def process_documentation_batch(
    files: List[Dict[str, str]], 
    dataset_name: str,
    project_root: str,
    job_id: Optional[str] = None  # Added for job tracking
) -> Dict[str, Any]:
    """
    Enqueues multiple file processing tasks for parallel execution.
    Now supports job tracking.
    
    Args:
        files: List of dicts with 'filepath' and 'commit_hash' keys
        dataset_name: Dataset to update
        project_root: Root directory of the project
        job_id: Optional job ID for progress tracking
        
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
            project_root=project_root,
            job_id=job_id  # Pass through job_id
        )
        task_ids.append(str(task.id))
    
    logger.info(f"Enqueued {len(files)} files for job {job_id}")
    
    return {
        "job_id": job_id,
        "batch_size": len(files),
        "task_ids": task_ids,
        "status": "enqueued"
    }

# Note: parse_claude_response has been moved to analysis.parser module

# Health check task for monitoring
@huey.task()
def health_check() -> Dict[str, Any]:
    """Simple task to verify worker is running."""
    logger.info("Health check executed")
    return {"status": "ok", "timestamp": os.environ.get('HUEY_WORKER_START_TIME', 'unknown')}