#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any
import logging

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize server
app = Server("code-query-mcp")

# Global database connection
db_conn = None

def init_database():
    """Initialize SQLite database and load JSON data"""
    global db_conn
    db_conn = sqlite3.connect(":memory:")
    db_conn.row_factory = sqlite3.Row
    cursor = db_conn.cursor()
    
    # Create table
    cursor.execute("""
        CREATE TABLE files (
            filepath TEXT PRIMARY KEY,
            filename TEXT,
            overview TEXT,
            functions TEXT,
            exports TEXT,
            imports TEXT,
            types_interfaces_classes TEXT,
            constants TEXT,
            ddd_context TEXT,
            dependencies TEXT,
            other_notes TEXT
        )
    """)
    
    # Load all JSON files
    data_dir = Path(__file__).parent.parent / "data"
    for json_file in data_dir.glob("agent_*.json"):
        with open(json_file, 'r') as f:
            data = json.load(f)
            for item in data:
                cursor.execute("""
                    INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item['filepath'],
                    item['filename'],
                    item['overview'],
                    json.dumps(item['functions']),
                    json.dumps(item['exports']),
                    json.dumps(item['imports']),
                    json.dumps(item['types_interfaces_classes']),
                    json.dumps(item['constants']),
                    item['ddd_context'],
                    json.dumps(item['dependencies']),
                    json.dumps(item['other_notes'])
                ))
    
    db_conn.commit()
    logger.info(f"Loaded {cursor.execute('SELECT COUNT(*) FROM files').fetchone()[0]} files into database")

@app.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools"""
    return [
        Tool(
            name="search_files",
            description="Search files by query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Maximum results (default: 10)", "default": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_file",
            description="Get complete file details",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "File path"}
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="list_domains",
            description="List all unique DDD contexts/domains",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls"""
    if name == "search_files":
        query = arguments["query"]
        limit = arguments.get("limit", 10)
        
        cursor = db_conn.cursor()
        results = cursor.execute("""
            SELECT filepath, filename, overview, ddd_context 
            FROM files 
            WHERE filename LIKE ? OR overview LIKE ? OR ddd_context LIKE ?
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        
        files = [dict(row) for row in results]
        return [TextContent(type="text", text=json.dumps(files, indent=2))]
    
    elif name == "get_file":
        filepath = arguments["filepath"]
        
        cursor = db_conn.cursor()
        row = cursor.execute("SELECT * FROM files WHERE filepath = ?", (filepath,)).fetchone()
        
        if row:
            result = dict(row)
            # Parse JSON fields back to objects
            for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 
                         'constants', 'dependencies', 'other_notes']:
                result[field] = json.loads(result[field])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({"error": "File not found"}))]
    
    elif name == "list_domains":
        cursor = db_conn.cursor()
        results = cursor.execute("SELECT DISTINCT ddd_context FROM files ORDER BY ddd_context").fetchall()
        domains = [row[0] for row in results]
        return [TextContent(type="text", text=json.dumps(domains, indent=2))]
    
    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

async def main():
    """Main entry point"""
    # Initialize database
    init_database()
    
    # Run server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())