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
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

# Import our refactored modules
from helpers.git_helper import get_git_info
from storage.sqlite_storage import CodeQueryServer
from tools.mcp_tools import get_tools

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database configuration - attempt to get Git repository information
git_info = get_git_info()

if git_info:
    # We are in a Git repository. Use the toplevel path for the DB.
    DB_DIR = os.path.join(git_info["toplevel_path"], ".mcp_code_query")
    DB_PATH = os.path.join(DB_DIR, "code_data.db")
    # Use a branch-specific prefix for tables to ensure data isolation
    TABLE_PREFIX = git_info["table_prefix"]
    logging.info(f"Git repo detected. Using shared DB at {DB_PATH}. Active data prefix: '{TABLE_PREFIX}'")
else:
    # Fallback for non-Git directories. Use the current working directory.
    DB_DIR = os.path.join(os.getcwd(), ".mcp_code_query")
    DB_PATH = os.path.join(DB_DIR, "code_data.db")
    # Use a default prefix when not in a git repo
    TABLE_PREFIX = "data_local"
    logging.info(f"No Git repo detected. Using local DB at {DB_PATH}.")

# Ensure the database directory exists
os.makedirs(DB_DIR, exist_ok=True)

# Initialize server
server = Server("code-query")
query_server = CodeQueryServer(DB_PATH, DB_DIR)


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
        result = query_server.get_project_config()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_pre_commit_hook":
        dataset_name = arguments.get("dataset_name", "")
        mode = arguments.get("mode", "queue")
        result = query_server.install_pre_commit_hook(dataset_name, mode)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "create_project_config":
        dataset_name = arguments.get("dataset_name", "")
        exclude_patterns = arguments.get("exclude_patterns")
        result = query_server.create_project_config(dataset_name, exclude_patterns)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "fork_dataset":
        source_dataset = arguments.get("source_dataset", "")
        target_dataset = arguments.get("target_dataset", "")
        result = query_server.fork_dataset(source_dataset, target_dataset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_post_merge_hook":
        main_dataset = arguments.get("main_dataset")
        result = query_server.install_post_merge_hook(main_dataset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Main entry point."""
    # Setup database connection (but don't load data)
    query_server.setup_database()
    
    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="code-query",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())