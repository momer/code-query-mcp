# Code Query MCP Server - Quick Build Specification

## Overview
Build a minimal MCP server that provides search capabilities over code review JSON files in any project.

## Data Source
- Looks for JSON files matching pattern `agent_*_review.json` in the current working directory
- Falls back to checking common locations: `tmp/index/`, `./`, `../`
- Each file contains an array of objects with: filename, filepath, overview, functions, exports, imports, types_interfaces_classes, constants, ddd_context, dependencies, other_notes

## Core Requirements

### 1. SQLite Database
- Load all JSON data on startup from CWD
- In-memory SQLite database (no persistence needed)
- Simple schema: files table with JSON columns for complex data
- Basic text search using LIKE queries

### 2. MCP Tools to Implement

```python
# 1. Search files by query
search_files(query: str, limit: int = 10) -> list[dict]
# Returns: [{filepath, filename, overview, ddd_context}, ...]

# 2. Get complete file details
get_file(filepath: str) -> dict
# Returns: Complete file object with all details

# 3. List all domains
list_domains() -> list[str]
# Returns: Unique list of ddd_context values

# 4. Get current data source (helpful for debugging)
get_data_source() -> dict
# Returns: {cwd: str, files_loaded: int, source_path: str}
```

### 3. Implementation Details
- Use `mcp.server.stdio` for MCP server
- Python 3.11+
- Dependencies: mcp, sqlite3 (built-in), glob, os
- Search for JSON files using `os.getcwd()` NOT relative to script location
- Search pattern: `glob.glob(os.path.join(os.getcwd(), "tmp/index/agent_*_review.json"))` 
- Also try: `glob.glob(os.path.join(os.getcwd(), "agent_*_review.json"))`
- Return results as JSON
- Graceful handling if no JSON files found

### 4. Quick Start Files Needed
- `server.py` - Main MCP server (not in src/ so it's easier to install globally)
- `requirements.txt` - Just "mcp"
- `README.md` - Installation and usage from any project

## Usage Pattern
User can install this MCP server globally, then use it in any project that has agent review files.

## Time Constraint
Build this in under 8 minutes. Focus on functionality over perfection.