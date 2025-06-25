#!/usr/bin/env python3
"""Code Query MCP Server - Search and query code review JSON files."""

import os
import json
import sqlite3
import glob
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database configuration
DB_DIR = os.path.join(os.getcwd(), ".mcp_code_query")
DB_PATH = os.path.join(DB_DIR, "code_data.db")


class CodeQueryServer:
    def __init__(self):
        self.db = None
        self.cwd = os.getcwd()
        # Ensure database directory exists
        os.makedirs(DB_DIR, exist_ok=True)
        
    def setup_database(self):
        """Connect to persistent SQLite database."""
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        
        # Check if schema exists
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files'
        """)
        
        if not cursor.fetchone():
            self._create_schema()
            logging.info(f"Created database schema at {DB_PATH}")
        else:
            logging.info(f"Connected to existing database at {DB_PATH}")
    
    def _create_schema(self):
        """Create database schema with dataset support."""
        # Main files table with dataset_id
        self.db.execute("""
            CREATE TABLE files (
                dataset_id TEXT NOT NULL,
                filepath TEXT NOT NULL,
                filename TEXT,
                overview TEXT,
                ddd_context TEXT,
                functions TEXT,
                exports TEXT,
                imports TEXT,
                types_interfaces_classes TEXT,
                constants TEXT,
                dependencies TEXT,
                other_notes TEXT,
                PRIMARY KEY (dataset_id, filepath)
            )
        """)
        
        # Index for efficient queries
        self.db.execute("""
            CREATE INDEX idx_dataset_filepath ON files(dataset_id, filepath)
        """)
        
        # Metadata table for tracking datasets
        self.db.execute("""
            CREATE TABLE dataset_metadata (
                dataset_id TEXT PRIMARY KEY,
                source_dir TEXT,
                files_count INTEGER,
                loaded_at TIMESTAMP
            )
        """)
        
        self.db.commit()
    
    def validate_directory(self, directory: str) -> str:
        """Validate and resolve directory path."""
        # Prevent absolute paths
        if os.path.isabs(directory):
            raise ValueError("Absolute paths not allowed")
        
        # Prevent parent directory traversal
        if ".." in directory:
            raise ValueError("Parent directory references not allowed")
        
        # Resolve full path
        full_path = os.path.join(self.cwd, directory)
        
        # Check if directory exists
        if not os.path.exists(full_path):
            raise ValueError(f"Directory not found: {directory}")
        
        if not os.path.isdir(full_path):
            raise ValueError(f"Not a directory: {directory}")
        
        return full_path
    
    def import_data(self, dataset_name: str, directory: str, replace: bool = False) -> Dict[str, Any]:
        """Import JSON files from directory into named dataset."""
        try:
            # Validate directory
            full_path = self.validate_directory(directory)
            
            # Check if dataset already exists
            existing = self.db.execute(
                "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if existing and not replace:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' already exists with {existing['files_count']} files. Use replace=true to overwrite."
                }
            
            # If replacing, delete existing data
            if existing and replace:
                self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
                self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
                self.db.commit()
            
            # Find JSON files
            patterns = [
                os.path.join(full_path, "agent_*_review.json"),
                os.path.join(full_path, "*.json")
            ]
            
            json_files = []
            for pattern in patterns:
                files = glob.glob(pattern)
                json_files.extend(files)
                if files:
                    break
            
            if not json_files:
                return {
                    "success": False,
                    "message": f"No JSON files found in {directory}"
                }
            
            # Load files
            files_loaded = 0
            errors = []
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                    
                    # Handle both single object and array formats
                    if isinstance(data, list):
                        for item in data:
                            if self._insert_file_data(dataset_name, item):
                                files_loaded += 1
                    else:
                        if self._insert_file_data(dataset_name, data):
                            files_loaded += 1
                            
                except Exception as e:
                    error_msg = f"Error loading {os.path.basename(json_file)}: {e}"
                    logging.error(error_msg)
                    errors.append(error_msg)
            
            # Update metadata
            self.db.execute("""
                INSERT OR REPLACE INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, ?, ?)
            """, (dataset_name, directory, files_loaded, datetime.now()))
            
            self.db.commit()
            
            result = {
                "success": True,
                "dataset_name": dataset_name,
                "files_loaded": files_loaded,
                "source": directory
            }
            
            if errors:
                result["errors"] = errors
            
            logging.info(f"Imported {files_loaded} files into dataset '{dataset_name}' from {directory}")
            return result
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def _insert_file_data(self, dataset_id: str, data: dict) -> bool:
        """Insert a single file's data into the database."""
        try:
            self.db.execute("""
                INSERT OR REPLACE INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dataset_id,
                data.get('filepath', ''),
                data.get('filename', ''),
                data.get('overview', ''),
                data.get('ddd_context', ''),
                json.dumps(data.get('functions', {})),
                json.dumps(data.get('exports', {})),
                json.dumps(data.get('imports', {})),
                json.dumps(data.get('types_interfaces_classes', {})),
                json.dumps(data.get('constants', {})),
                json.dumps(data.get('dependencies', [])),
                json.dumps(data.get('other_notes', []))
            ))
            return True
        except Exception as e:
            logging.error(f"Error inserting file data: {e}")
            return False
    
    def search_files(self, query: str, dataset_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search files in specific dataset by query string."""
        if not self.db:
            return []
        
        # Search in multiple fields
        cursor = self.db.execute("""
            SELECT filepath, filename, overview, ddd_context
            FROM files
            WHERE dataset_id = ? AND (
                filename LIKE ? OR filepath LIKE ? OR overview LIKE ? 
                OR ddd_context LIKE ? OR functions LIKE ? OR other_notes LIKE ?
            )
            LIMIT ?
        """, (
            dataset_name,
            f'%{query}%', f'%{query}%', f'%{query}%',
            f'%{query}%', f'%{query}%', f'%{query}%', limit
        ))
        
        results = []
        for row in cursor:
            results.append({
                'filepath': row['filepath'],
                'filename': row['filename'],
                'overview': row['overview'],
                'ddd_context': row['ddd_context']
            })
        
        return results
    
    def get_file(self, filepath: str, dataset_name: str) -> Optional[Dict[str, Any]]:
        """Get complete details for a specific file in dataset."""
        if not self.db:
            return None
        
        cursor = self.db.execute("""
            SELECT * FROM files 
            WHERE dataset_id = ? AND filepath = ?
        """, (dataset_name, filepath))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # Convert row to dict and parse JSON fields
        result = dict(row)
        for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants', 'dependencies', 'other_notes']:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except:
                    result[field] = {} if field not in ['dependencies', 'other_notes'] else []
        
        # Remove dataset_id from result (it's in the query)
        result.pop('dataset_id', None)
        
        return result
    
    def list_domains(self, dataset_name: str) -> List[str]:
        """List all unique DDD context domains in dataset."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT DISTINCT ddd_context FROM files
            WHERE dataset_id = ? AND ddd_context IS NOT NULL AND ddd_context != ''
            ORDER BY ddd_context
        """, (dataset_name,))
        
        return [row[0] for row in cursor]
    
    def list_datasets(self) -> List[Dict[str, Any]]:
        """List all loaded datasets."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT dataset_id, source_dir, files_count, loaded_at
            FROM dataset_metadata
            ORDER BY loaded_at DESC
        """)
        
        results = []
        for row in cursor:
            results.append({
                'name': row['dataset_id'],
                'source': row['source_dir'],
                'file_count': row['files_count'],
                'loaded_at': row['loaded_at']
            })
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current database status."""
        datasets = self.list_datasets()
        total_files = sum(d['file_count'] for d in datasets)
        
        return {
            'database_path': DB_PATH,
            'datasets': datasets,
            'total_files': total_files
        }
    
    def clear_dataset(self, dataset_name: str) -> Dict[str, Any]:
        """Clear a specific dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Check if dataset exists
        existing = self.db.execute(
            "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
            (dataset_name,)
        ).fetchone()
        
        if not existing:
            return {
                "success": False,
                "message": f"Dataset '{dataset_name}' not found"
            }
        
        # Delete data
        self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
        self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
        self.db.commit()
        
        return {
            "success": True,
            "message": f"Cleared dataset '{dataset_name}' with {existing['files_count']} files"
        }


# Initialize server
server = Server("code-query")
query_server = CodeQueryServer()


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools."""
    return [
        Tool(
            name="import_data",
            description="Import JSON files from directory into named dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path containing JSON files"
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "Replace existing dataset if it exists",
                        "default": False
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="search_files",
            description="Search files in dataset by query string",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10
                    }
                },
                "required": ["query", "dataset_name"]
            }
        ),
        types.Tool(
            name="get_file",
            description="Get complete details for a specific file",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file"
                    }
                },
                "required": ["filepath", "dataset_name"]
            }
        ),
        types.Tool(
            name="list_domains",
            description="List all unique DDD context domains in dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to analyze"
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        types.Tool(
            name="list_datasets",
            description="List all loaded datasets",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_status",
            description="Get current database status",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="clear_dataset",
            description="Clear a specific dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to clear"
                    }
                },
                "required": ["dataset_name"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    if name == "import_data":
        dataset_name = arguments.get("dataset_name", "")
        directory = arguments.get("directory", "")
        replace = arguments.get("replace", False)
        result = query_server.import_data(dataset_name, directory, replace)
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
        result = query_server.get_file(filepath, dataset_name)
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
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Main entry point."""
    # Setup database connection (but don't load data)
    query_server.setup_database()
    
    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        from mcp.server.models import InitializationOptions
        from mcp.server.lowlevel import NotificationOptions
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