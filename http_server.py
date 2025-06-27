#!/usr/bin/env python3
"""HTTP-based MCP Server for code-query-mcp."""

import asyncio
import json
import logging
import os
import uuid
from typing import Dict, Any, List, Optional
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# MCP imports
from mcp.server import Server
from mcp.types import Tool, TextContent

# Local imports
from helpers.git_helper import get_git_info, get_worktree_info
from storage.sqlite_storage import CodeQueryServer
from tools.mcp_tools import get_tools

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP requests."""
    
    def __init__(self, *args, mcp_server: Server, query_server: CodeQueryServer, **kwargs):
        self.mcp_server = mcp_server
        self.query_server = query_server
        # sessions will be defined at class level in create_handler_class
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info("%s - - [%s] %s" % (
            self.address_string(),
            self.log_date_time_string(),
            format % args
        ))
    
    def _send_cors_headers(self):
        """Send CORS headers for browser compatibility."""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, Mcp-Session-Id, MCP-Protocol-Version')
        self.send_header('Access-Control-Max-Age', '3600')
    
    def _validate_origin(self):
        """Validate Origin header to prevent DNS rebinding attacks."""
        origin = self.headers.get('Origin')
        if origin:
            # For local development, allow localhost and 127.0.0.1
            allowed_origins = ['http://localhost', 'http://127.0.0.1', 'https://localhost', 'https://127.0.0.1']
            
            # Check if origin starts with any allowed origin
            if not any(origin.startswith(allowed) for allowed in allowed_origins):
                logger.warning(f"Rejected request from origin: {origin}")
                return False
        return True
    
    def _get_session_id(self) -> Optional[str]:
        """Get session ID from headers."""
        return self.headers.get('Mcp-Session-Id')
    
    def _create_session(self) -> str:
        """Create a new session and return session ID."""
        import time
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'created_at': time.time(),
            'active_dataset': getattr(self.query_server, 'active_dataset', None)
        }
        return session_id
    
    def _validate_session(self, session_id: str) -> bool:
        """Validate that session exists."""
        return session_id in self.sessions
    
    def do_OPTIONS(self):
        """Handle preflight CORS requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests for SSE streams."""
        if not self._validate_origin():
            self.send_error(403, "Invalid origin")
            return
        
        # Parse URL
        parsed_url = urlparse(self.path)
        
        if parsed_url.path != '/mcp':
            self.send_error(404, "Not found")
            return
        
        accept_header = self.headers.get('Accept', '')
        if 'text/event-stream' not in accept_header:
            self.send_error(400, "Must accept text/event-stream")
            return
        
        # For now, we don't implement server-initiated SSE streams
        # Return 405 Method Not Allowed as per spec
        self.send_error(405, "Server-initiated SSE not implemented")
    
    def do_POST(self):
        """Handle POST requests with JSON-RPC messages."""
        if not self._validate_origin():
            self.send_error(403, "Invalid origin")
            return
        
        # Parse URL
        parsed_url = urlparse(self.path)
        
        if parsed_url.path != '/mcp':
            self.send_error(404, "Not found")
            return
        
        # Validate content type
        content_type = self.headers.get('Content-Type', '')
        if not content_type.startswith('application/json'):
            self.send_error(400, "Content-Type must be application/json")
            return
        
        # Validate Accept header
        accept_header = self.headers.get('Accept', '')
        if 'application/json' not in accept_header:
            self.send_error(400, "Must accept application/json")
            return
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_error(400, "Empty request body")
            return
        
        try:
            request_data = self.rfile.read(content_length).decode('utf-8')
            request_json = json.loads(request_data)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self.send_error(400, f"Invalid JSON: {e}")
            return
        
        # Handle session management
        session_id = self._get_session_id()
        
        # Check if this is an initialize request
        is_initialize = (
            isinstance(request_json, dict) and 
            request_json.get('method') == 'initialize'
        )
        
        if is_initialize:
            # Create new session for initialize
            session_id = self._create_session()
        elif session_id:
            # Validate existing session
            if not self._validate_session(session_id):
                self.send_error(404, "Session not found")
                return
        
        # Process the request
        try:
            # Debug logging
            logger.info(f"Received MCP request: {json.dumps(request_json, indent=2)}")
            response = self._handle_mcp_request(request_json, session_id)
            
            # Handle notifications that don't need a response
            if response is None:
                logger.info("No response needed (notification)")
                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()
                return
            
            logger.info(f"Sending MCP response: {json.dumps(response, indent=2)}")
            
            # Send response
            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            
            # Add session ID to response headers for initialize
            if is_initialize and session_id:
                self.send_header('Mcp-Session-Id', session_id)
            
            self.end_headers()
            
            response_data = json.dumps(response, ensure_ascii=False)
            self.wfile.write(response_data.encode('utf-8'))
            
        except Exception as e:
            logger.error(f"Error processing request: {e}", exc_info=True)
            self.send_error(500, "Internal server error")
    
    def do_DELETE(self):
        """Handle DELETE requests for session termination."""
        if not self._validate_origin():
            self.send_error(403, "Invalid origin")
            return
        
        session_id = self._get_session_id()
        if not session_id:
            self.send_error(400, "Session ID required")
            return
        
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.send_response(200)
            self._send_cors_headers()
            self.end_headers()
        else:
            self.send_error(404, "Session not found")
    
    def _handle_mcp_request(self, request_json: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
        """Handle MCP JSON-RPC request."""
        method = request_json.get('method')
        request_id = request_json.get('id')
        params = request_json.get('params', {})
        
        try:
            if method == 'initialize':
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {
                            "tools": {
                                "listChanged": True
                            }
                        },
                        "serverInfo": {
                            "name": "code-query",
                            "version": "1.1.0"
                        }
                    }
                }
            
            elif method == 'tools/list':
                tools = self._list_tools()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [tool.model_dump() for tool in tools]
                        # Note: nextCursor is omitted when there are no more pages
                    }
                }
            
            elif method == 'notifications/initialized':
                # Client has completed initialization - no response needed for notifications
                return None
            
            elif method == 'tools/call':
                tool_name = params.get('name', '')
                arguments = params.get('arguments', {})
                result = self._call_tool(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [content.model_dump() for content in result],
                        "isError": False
                    }
                }
            
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
        
        except Exception as e:
            logger.error(f"Error handling method {method}: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }
    
    def _list_tools(self) -> List[Tool]:
        """List available tools."""
        return get_tools()
    
    def _call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle tool calls - reuse logic from server.py."""
        if name == "import_data":
            dataset_name = arguments.get("dataset_name", "")
            directory = arguments.get("directory", "")
            replace = arguments.get("replace", False)
            result = self.query_server.import_data(dataset_name, directory, replace)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "recommend_setup":
            project_name = arguments.get("project_name")
            source_directory = arguments.get("source_directory")
            result = self.query_server.recommend_setup(project_name, source_directory)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "search_files":
            query = arguments.get("query", "")
            dataset_name = arguments.get("dataset_name", "")
            limit = arguments.get("limit", 10)
            results = self.query_server.search_files(query, dataset_name, limit)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "search":
            query = arguments.get("query", "")
            dataset_name = arguments.get("dataset_name", "")
            limit = arguments.get("limit", 10)
            results = self.query_server.search(query, dataset_name, limit)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "search_full_content":
            query = arguments.get("query", "")
            dataset_name = arguments.get("dataset_name", "")
            limit = arguments.get("limit", 10)
            results = self.query_server.search_full_content(query, dataset_name, limit)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "get_file":
            filepath = arguments.get("filepath", "")
            dataset_name = arguments.get("dataset_name", "")
            limit = arguments.get("limit", 10)
            result = self.query_server.get_file(filepath, dataset_name, limit)
            if result:
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            else:
                return [TextContent(type="text", text=json.dumps({"error": "File not found"}))]
        
        elif name == "list_domains":
            dataset_name = arguments.get("dataset_name", "")
            domains = self.query_server.list_domains(dataset_name)
            return [TextContent(type="text", text=json.dumps(domains, indent=2))]
        
        elif name == "list_datasets":
            datasets = self.query_server.list_datasets()
            return [TextContent(type="text", text=json.dumps(datasets, indent=2))]
        
        elif name == "get_status":
            status = self.query_server.get_status()
            return [TextContent(type="text", text=json.dumps(status, indent=2))]
        
        elif name == "clear_dataset":
            dataset_name = arguments.get("dataset_name", "")
            result = self.query_server.clear_dataset(dataset_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "document_directory":
            dataset_name = arguments.get("dataset_name", "")
            directory = arguments.get("directory", "")
            exclude_patterns = arguments.get("exclude_patterns", [])
            batch_size = arguments.get("batch_size", 20)
            result = self.query_server.document_directory(dataset_name, directory, exclude_patterns, batch_size)
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
            
            result = self.query_server.insert_file_documentation(
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
            
            result = self.query_server.update_file_documentation(
                dataset_name, filepath, filename, overview,
                functions, exports, imports, types_interfaces_classes,
                constants, ddd_context, dependencies, other_notes
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_project_config":
            result = self.query_server.get_project_config()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "install_pre_commit_hook":
            dataset_name = arguments.get("dataset_name", "")
            mode = arguments.get("mode", "queue")
            result = self.query_server.install_pre_commit_hook(dataset_name, mode)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "create_project_config":
            dataset_name = arguments.get("dataset_name", "")
            exclude_patterns = arguments.get("exclude_patterns")
            model = arguments.get("model")
            result = self.query_server.create_project_config(dataset_name, exclude_patterns, model)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "fork_dataset":
            source_dataset = arguments.get("source_dataset", "")
            target_dataset = arguments.get("target_dataset", "")
            result = self.query_server.fork_dataset(source_dataset, target_dataset)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "install_post_merge_hook":
            main_dataset = arguments.get("main_dataset")
            result = self.query_server.install_post_merge_hook(main_dataset)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "sync_dataset":
            source_dataset = arguments.get("source_dataset", "")
            target_dataset = arguments.get("target_dataset", "")
            source_ref = arguments.get("source_ref", "")
            target_ref = arguments.get("target_ref", "")
            result = self.query_server.sync_dataset(source_dataset, target_dataset, source_ref, target_ref)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "cleanup_datasets":
            dry_run = arguments.get("dry_run", True)
            result = self.query_server.cleanup_datasets(dry_run)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "find_files_needing_catchup":
            dataset_name = arguments.get("dataset_name")
            if not dataset_name:
                return [TextContent(type="text", text="dataset_name is required")]
            
            result = self.query_server.find_files_needing_catchup(dataset_name)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "backport_commit_to_file":
            dataset_name = arguments.get("dataset_name")
            filepath = arguments.get("filepath")
            commit_hash = arguments.get("commit_hash")
            
            if not all([dataset_name, filepath, commit_hash]):
                return [TextContent(type="text", text="dataset_name, filepath, and commit_hash are required")]
            
            result = self.query_server.backport_commit_to_file(dataset_name, filepath, commit_hash)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "bulk_backport_commits":
            dataset_name = arguments.get("dataset_name")
            commit_hash = arguments.get("commit_hash")  # Optional
            
            if not dataset_name:
                return [TextContent(type="text", text="dataset_name is required")]
            
            result = self.query_server.bulk_backport_commits(dataset_name, commit_hash)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


def create_handler_class(mcp_server: Server, query_server: CodeQueryServer):
    """Create handler class with injected dependencies."""
    class Handler(MCPHTTPHandler):
        # Class-level sessions dictionary shared across all handler instances
        sessions: Dict[str, Dict[str, Any]] = {}
        
        def __init__(self, *args, **kwargs):
            super().__init__(*args, mcp_server=mcp_server, query_server=query_server, **kwargs)
    return Handler


def start_http_server(query_server: CodeQueryServer, host='127.0.0.1', port=8000):
    """Start the HTTP server."""
    # Initialize server components
    mcp_server = Server("code-query")
    
    # Create handler class
    handler_class = create_handler_class(mcp_server, query_server)
    
    # Start HTTP server
    server = HTTPServer((host, port), handler_class)
    logger.info(f"Starting HTTP MCP server on {host}:{port}")
    logger.info(f"MCP endpoint available at: http://{host}:{port}/mcp")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.shutdown()


if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    host = '127.0.0.1'
    port = 8000
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    if len(sys.argv) > 2:
        host = sys.argv[2]
    
    start_http_server(host, port)
