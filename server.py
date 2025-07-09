#!/usr/bin/env python3
"""Code Query MCP Server - Search and query code review JSON files.

Dataset Discovery Pattern:
When using any tool that requires a dataset_name parameter, if the dataset name
is unknown, use the list_datasets tool first to discover available datasets.
This ensures Claude can always find the appropriate dataset for the current project.
"""

import os
import json
import logging
from typing import List, Dict, Any
from mcp.server import Server
from mcp.types import Tool, TextContent, InitializeRequestParams
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

# Import our refactored modules
from helpers.git_helper import get_git_info, get_worktree_info, get_main_worktree_path
from storage.sqlite_storage import CodeQueryServer
from tools.mcp_tools import get_tools
from config.config_service import ConfigurationService
from config.project_config import HookType
from config.utils import check_jq_installed

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database configuration - attempt to get Git repository information
# Use client root directory if available, otherwise current working directory
client_root = os.environ.get('MCP_CLIENT_ROOT', os.getcwd())
git_info = get_git_info(cwd=client_root)

if git_info:
    # We are in a Git repository. Use the toplevel path for the DB.
    DB_DIR = os.path.join(git_info["toplevel_path"], ".mcp_code_query")
    DB_PATH = os.path.join(DB_DIR, "code_data.db")
    logging.info(f"Git repo detected. Using shared DB at {DB_PATH}")
else:
    # Fallback for non-Git directories. Use the client root directory.
    DB_DIR = os.path.join(client_root, ".mcp_code_query")
    DB_PATH = os.path.join(DB_DIR, "code_data.db")
    logging.info(f"No Git repo detected. Using local DB at {DB_PATH}.")

# Ensure the database directory exists
os.makedirs(DB_DIR, exist_ok=True)

# Initialize server
server = Server("code-query")
query_server = CodeQueryServer(storage_backend=None, db_path=DB_PATH, db_dir=DB_DIR)
config_service = ConfigurationService(DB_DIR)



@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools."""
    return get_tools()


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    if name == "import_data":
        dataset_name = arguments.get("dataset_name", "")
        directory = arguments.get("directory", "")
        replace = arguments.get("replace", False)
        result = query_server.import_data(dataset_name, directory, replace)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "recommend_setup":
        project_name = arguments.get("project_name")
        source_directory = arguments.get("source_directory")
        result = query_server.recommend_setup(project_name, source_directory)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "search_files":
        query = arguments.get("query", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        results = query_server.search_files(query, dataset_name, limit)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "search":
        query = arguments.get("query", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        results = query_server.search(query, dataset_name, limit)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "search_full_content":
        query = arguments.get("query", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        results = query_server.search_full_content(query, dataset_name, limit)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "get_file":
        filepath = arguments.get("filepath", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        result = query_server.get_file(filepath, dataset_name, limit)
        if result:
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({"error": "File not found"}))]
    
    elif name == "list_domains":
        dataset_name = arguments.get("dataset_name", "")
        domains = query_server.list_domains(dataset_name)
        return [TextContent(type="text", text=json.dumps(domains, indent=2))]
    
    elif name == "list_datasets":
        datasets = query_server.list_datasets()
        return [TextContent(type="text", text=json.dumps(datasets, indent=2))]
    
    elif name == "get_status":
        status = query_server.get_status()
        return [TextContent(type="text", text=json.dumps(status, indent=2))]
    
    elif name == "clear_dataset":
        dataset_name = arguments.get("dataset_name", "")
        result = query_server.clear_dataset(dataset_name)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "document_directory":
        dataset_name = arguments.get("dataset_name", "")
        directory = arguments.get("directory", "")
        exclude_patterns = arguments.get("exclude_patterns", [])
        batch_size = arguments.get("batch_size", 20)
        result = query_server.document_directory(dataset_name, directory, exclude_patterns, batch_size)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "insert_file_documentation":
        dataset_name = arguments.get("dataset_name", "")
        filepath = arguments.get("filepath", "")
        filename = arguments.get("filename", "")
        overview = arguments.get("overview", "")
        functions = arguments.get("functions", {})
        exports = arguments.get("exports", {})
        imports = arguments.get("imports", {})
        types_interfaces_classes = arguments.get("types_interfaces_classes", {})
        constants = arguments.get("constants", {})
        ddd_context = arguments.get("ddd_context", "")
        dependencies = arguments.get("dependencies", [])
        other_notes = arguments.get("other_notes", [])
        
        result = query_server.insert_file_documentation(
            dataset_name, filepath, filename, overview,
            functions, exports, imports, types_interfaces_classes,
            constants, ddd_context, dependencies, other_notes
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "update_file_documentation":
        dataset_name = arguments.get("dataset_name", "")
        filepath = arguments.get("filepath", "")
        filename = arguments.get("filename")
        overview = arguments.get("overview")
        functions = arguments.get("functions")
        exports = arguments.get("exports")
        imports = arguments.get("imports")
        types_interfaces_classes = arguments.get("types_interfaces_classes")
        constants = arguments.get("constants")
        ddd_context = arguments.get("ddd_context")
        dependencies = arguments.get("dependencies")
        other_notes = arguments.get("other_notes")
        
        result = query_server.update_file_documentation(
            dataset_name, filepath, filename, overview,
            functions, exports, imports, types_interfaces_classes,
            constants, ddd_context, dependencies, other_notes
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "get_project_config":
        # Use new configuration service
        config = config_service.get_config()
        status = config_service.get_configuration_status()
        
        # Get database status from query_server
        db_status = query_server.get_status()
        
        # Build response compatible with existing interface
        result = {
            "success": True,
            "project_root": str(config_service.base_path),
            "config_file": {
                "exists": status.is_configured,
                "path": status.config_path if status.is_configured else None,
                "content": config.to_dict() if config else None
            },
            "git": {
                "is_repository": len(status.hooks_installed) >= 0,  # GitHookManager validates git
                "hooks": {
                    "pre_commit": HookType.PRE_COMMIT in status.hooks_installed,
                    "post_merge": HookType.POST_MERGE in status.hooks_installed
                }
            },
            "database": db_status,
            "setup_complete": status.is_configured and (db_status.get('dataset_count', 0) > 0)
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_pre_commit_hook":
        dataset_name = arguments.get("dataset_name", "")
        mode = arguments.get("mode", "queue")
        
        # Check if jq is installed (required by current hooks)
        jq_installed, jq_error = check_jq_installed()
        if not jq_installed:
            result = {
                "success": False,
                **jq_error
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Install hook using new service
        success, message = config_service.install_git_hook(
            HookType.PRE_COMMIT,
            dataset_name=dataset_name,
            mode=mode
        )
        
        result = {
            "success": success,
            "message": message
        }
        
        if success:
            hook_path = config_service.git_manager.get_hook_path(HookType.PRE_COMMIT)
            if hook_path:
                result["hook_path"] = str(hook_path)
            result["next_steps"] = [
                "The pre-commit hook will queue changed files for documentation",
                "Run document_directory to process queued files"
            ]
            
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "create_project_config":
        dataset_name = arguments.get("dataset_name", "")
        exclude_patterns = arguments.get("exclude_patterns")
        model = arguments.get("model")
        
        # Check for worktree and handle dataset forking
        wt_info = get_worktree_info(config_service.base_path)
        actual_dataset_name = dataset_name
        auto_fork_info = None
        
        if wt_info and wt_info['is_worktree']:
            # Handle worktree-specific dataset naming and forking
            main_path = wt_info['main_path']
            sanitized_branch = wt_info['sanitized_branch']
            
            # Try to find main dataset from main worktree's config
            main_config_service = ConfigurationService(main_path)
            main_config = main_config_service.get_config()
            main_dataset = main_config.default_dataset if main_config else dataset_name
            
            # Log worktree detection for debugging
            logging.info(f"Worktree detected: branch={wt_info['branch']}, main_dataset={main_dataset}")
            
            # Create worktree-specific dataset name
            wt_dataset_name = f"{main_dataset}_{sanitized_branch}"
            logging.info(f"Worktree dataset name: {wt_dataset_name}")
            
            # Check if we need to fork the dataset
            if query_server.db:
                cursor = query_server.db.execute(
                    "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?",
                    (wt_dataset_name,)
                )
                wt_exists = cursor.fetchone()['count'] > 0
                
                if not wt_exists:
                    # Check if main dataset exists to fork from
                    cursor = query_server.db.execute(
                        "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?",
                        (main_dataset,)
                    )
                    main_exists = cursor.fetchone()['count'] > 0
                    
                    if main_exists:
                        # Fork the main dataset
                        fork_result = query_server.fork_dataset(main_dataset, wt_dataset_name)
                        if fork_result['success']:
                            auto_fork_info = {
                                "forked": True,
                                "from": main_dataset,
                                "to": wt_dataset_name,
                                "files": fork_result.get('files_copied', 0)
                            }
            
            actual_dataset_name = wt_dataset_name
        
        # Create config using new service
        try:
            config = config_service.create_config(
                project_name=dataset_name,
                default_dataset=actual_dataset_name,
                ignored_patterns=exclude_patterns or None
            )
            
            # Build response with worktree information
            response = {
                "success": True,
                "message": f"Created project configuration for dataset '{actual_dataset_name}'",
                "config_path": str(config_service.storage.config_path),
                "config": config.to_dict()
            }
            
            # Add worktree-specific information
            if wt_info and wt_info['is_worktree']:
                if auto_fork_info:
                    response["message"] = (
                        f"✅ Git worktree detected! Created isolated dataset '{actual_dataset_name}' "
                        f"for branch '{wt_info['branch']}' by copying {auto_fork_info['files']} files "
                        f"from main dataset '{auto_fork_info['from']}'."
                    )
                else:
                    response["message"] = (
                        f"✅ Git worktree detected! Created configuration for isolated dataset "
                        f"'{actual_dataset_name}' for branch '{wt_info['branch']}'."
                    )
                    
                response["worktree_dataset_info"] = {
                    "note": "This is a git worktree - data will be stored in a separate dataset",
                    "worktree_dataset": actual_dataset_name,
                    "main_dataset": main_dataset,
                    "branch": wt_info['branch'],
                    "data_isolation": "All operations in this worktree will use the worktree-specific dataset",
                    "important": f"IMPORTANT: Your data was {'copied from' if auto_fork_info else 'will be isolated from'} the main dataset. Changes in this worktree will not affect the main dataset."
                }
                
            if auto_fork_info:
                response["auto_fork_info"] = auto_fork_info
                
        except Exception as e:
            response = {
                "success": False,
                "message": f"Error creating project config: {str(e)}"
            }
            
        return [TextContent(type="text", text=json.dumps(response, indent=2))]
    
    elif name == "fork_dataset":
        source_dataset = arguments.get("source_dataset", "")
        target_dataset = arguments.get("target_dataset", "")
        result = query_server.fork_dataset(source_dataset, target_dataset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_post_merge_hook":
        main_dataset = arguments.get("main_dataset")
        
        # Check if jq is installed (required by post-merge hook)
        jq_installed, jq_error = check_jq_installed()
        if not jq_installed:
            result = {
                "success": False,
                **jq_error
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # If no main dataset provided, try to get from config
        if not main_dataset:
            config = config_service.get_config()
            if config:
                main_dataset = config.default_dataset
                
        if not main_dataset:
            result = {
                "success": False,
                "message": "No main dataset specified and couldn't find one in config."
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Install hook using new service
        success, message = config_service.install_git_hook(
            HookType.POST_MERGE,
            dataset_name=main_dataset
        )
        
        result = {
            "success": success,
            "message": message
        }
        
        if success:
            hook_path = config_service.git_manager.get_hook_path(HookType.POST_MERGE)
            if hook_path:
                result["hook_path"] = str(hook_path)
            result["next_steps"] = [
                "The post-merge hook will detect when you merge in a worktree",
                "It will suggest the sync_dataset command to run",
                "This helps keep main dataset updated with worktree changes"
            ]
            
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "sync_dataset":
        source_dataset = arguments.get("source_dataset", "")
        target_dataset = arguments.get("target_dataset", "")
        source_ref = arguments.get("source_ref", "")
        target_ref = arguments.get("target_ref", "")
        result = query_server.sync_dataset(source_dataset, target_dataset, source_ref, target_ref)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "cleanup_datasets":
        dry_run = arguments.get("dry_run", True)
        result = query_server.cleanup_datasets(dry_run)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "find_files_needing_catchup":
        dataset_name = arguments.get("dataset_name")
        if not dataset_name:
            return [TextContent(type="text", text="dataset_name is required")]
        
        result = query_server.find_files_needing_catchup(dataset_name)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "backport_commit_to_file":
        dataset_name = arguments.get("dataset_name")
        filepath = arguments.get("filepath")
        commit_hash = arguments.get("commit_hash")
        
        if not all([dataset_name, filepath, commit_hash]):
            return [TextContent(type="text", text="dataset_name, filepath, and commit_hash are required")]
        
        result = query_server.backport_commit_to_file(dataset_name, filepath, commit_hash)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "bulk_backport_commits":
        dataset_name = arguments.get("dataset_name")
        commit_hash = arguments.get("commit_hash")  # Optional
        
        if not dataset_name:
            return [TextContent(type="text", text="dataset_name is required")]
        
        result = query_server.bulk_backport_commits(dataset_name, commit_hash)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


def setup_query_server():
    """Setup and configure the query server."""
    # Setup database connection
    query_server.setup_database()
    
    # Detect worktree and setup appropriate dataset
    worktree_info = get_worktree_info()
    active_dataset_name = None
    
    if worktree_info:
        # We're in a git repository
        if worktree_info["is_worktree"]:
            # This is a linked worktree - need to check main config
            main_config_path = os.path.join(worktree_info["main_path"], ".code-query", "config.json")
            
            if os.path.exists(main_config_path):
                try:
                    with open(main_config_path, 'r') as f:
                        main_config = json.load(f)
                    
                    # Support both old and new config schema
                    main_dataset_name = main_config.get("mainDatasetName") or main_config.get("datasetName")
                    
                    if main_dataset_name:
                        # Derive worktree dataset name - use cleaner naming without __wt_
                        worktree_dataset_name = f"{main_dataset_name}_{worktree_info['sanitized_branch']}"
                        
                        # Check if worktree dataset exists
                        existing_datasets = {d['name'] for d in query_server.list_datasets()}
                        
                        if worktree_dataset_name not in existing_datasets:
                            logging.info(f"Creating worktree dataset '{worktree_dataset_name}' from '{main_dataset_name}'...")
                            fork_result = query_server.fork_dataset(main_dataset_name, worktree_dataset_name)
                            
                            if not fork_result.get("success"):
                                logging.error(f"Failed to fork dataset: {fork_result.get('message')}")
                                logging.info(f"Falling back to main dataset '{main_dataset_name}'")
                                active_dataset_name = main_dataset_name
                            else:
                                logging.info(f"Successfully created worktree dataset '{worktree_dataset_name}'")
                                active_dataset_name = worktree_dataset_name
                        else:
                            logging.info(f"Using existing worktree dataset '{worktree_dataset_name}'")
                            active_dataset_name = worktree_dataset_name
                    else:
                        logging.warning("No mainDatasetName found in main config. Please run setup on main branch first.")
                except Exception as e:
                    logging.error(f"Error reading main config: {e}")
            else:
                logging.warning("No config found in main worktree. Please run setup on main branch first.")
        else:
            # This is the main worktree - check local config
            local_config_path = os.path.join(os.getcwd(), ".code-query", "config.json")
            if os.path.exists(local_config_path):
                try:
                    with open(local_config_path, 'r') as f:
                        config = json.load(f)
                    active_dataset_name = config.get("mainDatasetName") or config.get("datasetName")
                except Exception as e:
                    logging.error(f"Error reading config: {e}")
    
    if active_dataset_name:
        logging.info(f"Active dataset for this session: '{active_dataset_name}'")
        # Store the active dataset name on the query_server for tool use
        query_server.active_dataset = active_dataset_name
    else:
        logging.info("No active dataset configured. Tools will require explicit dataset names.")

def main_sync():
    """Main entry point for sync execution."""
    # Check command line arguments for transport type
    import sys
    
    transport_mode = "stdio"  # default
    http_port = 8000
    http_host = "127.0.0.1"
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--http":
            transport_mode = "http"
            if len(sys.argv) > 2:
                http_port = int(sys.argv[2])
            if len(sys.argv) > 3:
                http_host = sys.argv[3]
    
    # Setup query server
    setup_query_server()
    
    # Run the server based on transport mode
    if transport_mode == "http":
        # Import and start HTTP server
        from http_server import start_http_server
        logging.info(f"Starting HTTP server on {http_host}:{http_port}")
        start_http_server(query_server, http_host, http_port)
    else:
        # Use stdio transport (default) - run in async mode
        import asyncio
        asyncio.run(main_async())

async def main_async():
    """Main entry point for async stdio execution."""
    # Setup query server
    setup_query_server()
    
    # Use stdio transport (default)
    logging.info("Starting stdio server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="code-query",
                server_version="1.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    main_sync()