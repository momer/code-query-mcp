#!/usr/bin/env python3
"""Code Query MCP Server - Search and query code review JSON files.

Dataset Discovery Pattern:
When using any tool that requires a dataset_name parameter, if the dataset name
is unknown, use the list_datasets tool first to discover available datasets.
This ensures Claude can always find the appropriate dataset for the current project.
"""

import os
import json
import sqlite3
import glob
import logging
import fnmatch
from datetime import datetime
from typing import List, Dict, Any, Optional
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

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
            raise ValueError("Absolute paths are not allowed for security reasons.")
        
        # Resolve the real path to guard against traversal attacks
        # os.path.normpath is not enough, realpath resolves '..' and symlinks
        full_path = os.path.realpath(os.path.join(self.cwd, directory))
        cwd_real = os.path.realpath(self.cwd)
        
        if not full_path.startswith(cwd_real):
            raise ValueError("Path traversal attempt detected. Only subdirectories are allowed.")
        
        # Check if directory exists
        if not os.path.isdir(full_path):
            raise ValueError(f"Directory not found or is not a directory: {directory}")
        
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
            
            # Use a set to avoid duplicates if a file matches multiple patterns
            json_files = set()
            for pattern in patterns:
                json_files.update(glob.glob(pattern))
            
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
    
    def get_file(self, filepath: str, dataset_name: str, limit: int = 10) -> Optional[Dict[str, Any] | List[Dict[str, Any]]]:
        """Get complete details for a specific file in dataset.
        
        Supports partial matching - if filepath doesn't contain %, it will be wrapped with % for LIKE query.
        Returns single file dict if exact match, list of files if multiple matches.
        """
        if not self.db:
            return None
        
        # If filepath doesn't contain wildcards, wrap with % for flexible matching
        if '%' not in filepath:
            # Try exact match first
            cursor = self.db.execute("""
                SELECT * FROM files 
                WHERE dataset_id = ? AND filepath = ?
            """, (dataset_name, filepath))
            
            row = cursor.fetchone()
            if row:
                # Exact match found, return single result
                result = dict(row)
                for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants', 'dependencies', 'other_notes']:
                    if result.get(field):
                        try:
                            result[field] = json.loads(result[field])
                        except (json.JSONDecodeError, TypeError):
                            logging.warning(f"Could not parse JSON for field '{field}' in file '{filepath}'. Using default value.")
                            result[field] = {} if field not in ['dependencies', 'other_notes'] else []
                result.pop('dataset_id', None)
                return result
            
            # No exact match, try partial matching
            filepath = f'%{filepath}%'
        
        # Use LIKE query for partial matching
        cursor = self.db.execute("""
            SELECT * FROM files 
            WHERE dataset_id = ? AND filepath LIKE ?
            LIMIT ?
        """, (dataset_name, filepath, limit))
        
        rows = cursor.fetchall()
        if not rows:
            return None
        
        # Convert rows to list of dicts and parse JSON fields
        results = []
        for row in rows:
            result = dict(row)
            for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants', 'dependencies', 'other_notes']:
                if result.get(field):
                    try:
                        result[field] = json.loads(result[field])
                    except (json.JSONDecodeError, TypeError):
                        logging.warning(f"Could not parse JSON for field '{field}' in file '{result['filepath']}'. Using default value.")
                        result[field] = {} if field not in ['dependencies', 'other_notes'] else []
            result.pop('dataset_id', None)
            results.append(result)
        
        # If only one result, return it directly for backward compatibility
        if len(results) == 1:
            return results[0]
        
        return results
    
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
    
    def _scan_directory(self, directory: str, exclude_patterns: List[str] = None) -> List[str]:
        """Scan directory for code files, respecting exclusion patterns."""
        exclude_patterns = exclude_patterns or []
        
        # Default exclude patterns
        default_excludes = ['node_modules', '.git', '.venv', '__pycache__', '*.pyc', '*.pyo']
        all_excludes = default_excludes + exclude_patterns
        
        # Supported file extensions
        code_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.astro', '.vue', '.svelte'}
        
        files = []
        for root, dirs, filenames in os.walk(directory):
            # Remove excluded directories from dirs to prevent walking into them
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pattern) for pattern in all_excludes)]
            
            for filename in filenames:
                # Check if file should be excluded
                if any(fnmatch.fnmatch(filename, pattern) for pattern in all_excludes):
                    continue
                
                # Check if file has supported extension
                if any(filename.endswith(ext) for ext in code_extensions):
                    rel_path = os.path.relpath(os.path.join(root, filename), directory)
                    files.append(rel_path)
        
        return sorted(files)
    
    def document_directory(self, dataset_name: str, directory: str, 
                         exclude_patterns: List[str] = None, batch_size: int = 20) -> Dict[str, Any]:
        """Generate instructions for Claude to orchestrate documentation of a directory."""
        try:
            # Validate directory
            full_path = self.validate_directory(directory)
            
            # Check if dataset already exists
            existing = self.db.execute(
                "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if existing:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' already exists. Please choose a different name or clear the existing dataset first."
                }
            
            # Create dataset entry
            self.db.execute("""
                INSERT INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, ?, ?)
            """, (dataset_name, directory, 0, datetime.now()))
            self.db.commit()
            
            # Scan directory for files
            files = self._scan_directory(full_path, exclude_patterns)
            
            if not files:
                # Remove the empty dataset
                self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
                self.db.commit()
                return {
                    "success": False,
                    "message": f"No code files found in {directory}"
                }
            
            # Create batches
            batches = {}
            for i in range(0, len(files), batch_size):
                batch_num = (i // batch_size) + 1
                batches[f"batch_{batch_num}"] = files[i:i + batch_size]
            
            # Generate instructions
            instructions = f"""I'll help you document the codebase in '{directory}' with {len(files)} files divided into {len(batches)} batches.

Please create {len(batches)} subagents to analyze the code files in parallel. Each agent should:

1. Process their assigned batch of files
2. For each file, analyze the code and extract:
   - Overview (1-3 sentences about the file's purpose)
   - Functions with parameters, returns, and purpose
   - Exports and what they provide
   - Imports and their sources
   - Types, interfaces, and classes
   - Constants and their purposes
   - DDD context (based on directory structure)
   - Dependencies (external libraries used)
   - Other relevant notes

3. Use the code-query MCP insert_file_documentation tool to store each file's analysis:
   "Use code-query MCP insert_file_documentation with dataset_name='{dataset_name}' and the file details"

4. Report completion status for tracking

The agents should respect DDD boundaries and understand the broader application context when analyzing files."""

            agent_template = """You are Agent {{AGENT_ID}} analyzing code files for documentation.

Your assigned files from '{directory}':
{{FILE_LIST}}

For each file:
1. Read and analyze the code thoroughly
2. Extract all relevant metadata (functions, types, imports, etc.)
3. Understand the file's role in the DDD architecture
4. Store the analysis using:
   "Use code-query MCP insert_file_documentation tool with dataset_name='{dataset_name}', filepath='{{FILEPATH}}', and all the extracted details"

Focus on being concise but comprehensive. Identify the core purpose and key elements of each file."""

            mcp_insert_template = {
                "tool": "insert_file_documentation",
                "parameters": {
                    "dataset_name": dataset_name,
                    "filepath": "path/to/file.ts",
                    "filename": "file.ts",
                    "overview": "Brief description of file purpose",
                    "functions": {
                        "functionName": {
                            "purpose": "What it does",
                            "parameters": ["param1: string", "param2: number"],
                            "returns": "ReturnType"
                        }
                    },
                    "exports": {
                        "exportName": "Description of export"
                    },
                    "imports": {
                        "from": ["what", "is", "imported"]
                    },
                    "types_interfaces_classes": {
                        "TypeName": "Description or definition"
                    },
                    "constants": {
                        "CONST_NAME": "Value or description"
                    },
                    "ddd_context": "domain-name",
                    "dependencies": ["react", "lodash"],
                    "other_notes": ["Additional observations"]
                }
            }
            
            return {
                "success": True,
                "dataset_name": dataset_name,
                "directory": directory,
                "total_files": len(files),
                "batch_count": len(batches),
                "batch_size": batch_size,
                "files_by_batch": batches,
                "instructions": instructions,
                "agent_template": agent_template.format(directory=directory, dataset_name=dataset_name),
                "mcp_insert_example": mcp_insert_template,
                "next_steps": [
                    f"Create {len(batches)} subagents",
                    "Assign each agent their batch of files",
                    "Agents analyze and insert documentation for each file",
                    "Monitor progress and handle any errors",
                    "Verify all files were processed successfully"
                ]
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def insert_file_documentation(self, dataset_name: str, filepath: str, filename: str,
                                overview: str, functions: Dict[str, Any] = None,
                                exports: Dict[str, str] = None, imports: Dict[str, List[str]] = None,
                                types_interfaces_classes: Dict[str, str] = None,
                                constants: Dict[str, str] = None, ddd_context: str = "",
                                dependencies: List[str] = None, other_notes: List[str] = None) -> Dict[str, Any]:
        """Insert file documentation analyzed by agents."""
        try:
            # Check if dataset exists
            existing = self.db.execute(
                "SELECT dataset_id FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if not existing:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' not found. Please create it first using document_directory."
                }
            
            # Prepare data for insertion
            data = {
                'filepath': filepath,
                'filename': filename,
                'overview': overview,
                'ddd_context': ddd_context or self._extract_ddd_context(filepath),
                'functions': functions or {},
                'exports': exports or {},
                'imports': imports or {},
                'types_interfaces_classes': types_interfaces_classes or {},
                'constants': constants or {},
                'dependencies': dependencies or [],
                'other_notes': other_notes or []
            }
            
            # Insert the file data
            if self._insert_file_data(dataset_name, data):
                # Update file count
                self.db.execute("""
                    UPDATE dataset_metadata 
                    SET files_count = (
                        SELECT COUNT(*) FROM files WHERE dataset_id = ?
                    )
                    WHERE dataset_id = ?
                """, (dataset_name, dataset_name))
                self.db.commit()
                
                return {
                    "success": True,
                    "message": f"Successfully inserted documentation for {filepath}"
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to insert documentation for {filepath}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Error inserting documentation: {str(e)}"
            }
    
    def _extract_ddd_context(self, filepath: str) -> str:
        """Extract DDD context from filepath based on directory structure."""
        parts = filepath.split('/')
        
        # Look for common DDD patterns
        if 'features' in parts:
            idx = parts.index('features')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        elif 'domains' in parts:
            idx = parts.index('domains')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        elif 'modules' in parts:
            idx = parts.index('modules')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        
        # Default to first meaningful directory
        for part in parts:
            if part not in ['src', 'lib', 'app'] and not part.startswith('.'):
                return part
        
        return ""


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
            description="Search files in dataset by query string. Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in. Use list_datasets tool if unknown."
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
        Tool(
            name="get_file",
            description="Get complete details for a specific file. Supports partial path matching (e.g., 'login.ts' finds 'src/auth/login.ts'). Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Full or partial path to the file. Use % for wildcards."
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use list_datasets tool if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results for partial matches",
                        "default": 10
                    }
                },
                "required": ["filepath", "dataset_name"]
            }
        ),
        Tool(
            name="list_domains",
            description="List all unique DDD context domains in dataset. Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to analyze. Use list_datasets tool if unknown."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="list_datasets",
            description="List all loaded datasets with their names, sources, and file counts. Use this when you need to discover available dataset names.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_status",
            description="Get current database status",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_dataset",
            description="Clear a specific dataset. Use list_datasets to see available datasets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to clear. Use list_datasets tool to see available options."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="document_directory",
            description="Generate orchestration instructions for documenting a directory of code files",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path to document"
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., '*.test.js', 'temp/*')"
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of files per agent batch",
                        "default": 20
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="insert_file_documentation",
            description="Insert analyzed file documentation into dataset (used by agents)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to insert into. Use list_datasets tool if unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path"
                    },
                    "filename": {
                        "type": "string",
                        "description": "File name"
                    },
                    "overview": {
                        "type": "string",
                        "description": "Brief file overview"
                    },
                    "functions": {
                        "type": "object",
                        "description": "Functions with their details"
                    },
                    "exports": {
                        "type": "object",
                        "description": "Exported items"
                    },
                    "imports": {
                        "type": "object",
                        "description": "Imported items"
                    },
                    "types_interfaces_classes": {
                        "type": "object",
                        "description": "Type definitions"
                    },
                    "constants": {
                        "type": "object",
                        "description": "Constant definitions"
                    },
                    "ddd_context": {
                        "type": "string",
                        "description": "DDD domain context"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "External dependencies"
                    },
                    "other_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional notes"
                    }
                },
                "required": ["dataset_name", "filepath", "filename", "overview"]
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