from huey import SqliteHuey
import subprocess
import json
import os
import logging
from typing import Dict, Any, Optional, List
from storage.sqlite_storage import CodeQueryServer

# Configure logging for tasks
logger = logging.getLogger('code-query.tasks')
logger.setLevel(logging.INFO)

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
            error_msg = f"Claude processing failed: {result.stderr}"
            logger.error(f"✗ Failed to document {filepath}: {error_msg}")
            raise Exception(error_msg)
            
    except Exception as e:
        logger.error(f"✗ Error processing {filepath}: {str(e)}")
        return {"success": False, "filepath": filepath, "error": str(e)}

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

# Add file handler for worker logs - will be initialized when worker starts
def setup_logging(project_root: str):
    """
    Set up logging for the worker process.
    Should be called when the worker starts.
    """
    log_dir = os.path.join(project_root, '.code-query')
    os.makedirs(log_dir, exist_ok=True)
    
    handler = logging.FileHandler(os.path.join(log_dir, 'worker.log'))
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)